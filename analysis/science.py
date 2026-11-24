"""Run audit, hypothesis tests, division of work, directions and selected conversations for Zugrama Residency.

Reads the frozen project snapshot, the run database (read-only), the raw request/response
audit and the retrospective family classification. Writes static/data/science.json.
Time is reported in *active* hours: global pauses (no model call from anyone for > 10 min)
are removed from the clock.

Usage:  python analysis/science.py [--labels names|codes]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sqlite3
import sys

import numpy as np
from scipy import stats as ss
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer
from statsmodels.stats.contingency_tables import StratifiedTable

sys.path.insert(0, os.path.dirname(__file__))
import stats as S  # noqa: E402
from build_data import DB, FAMILIES, SITE, SNAP, WS, category, parse_run  # noqa: E402

AUDIT = WS / "residency_app/.data/project-completion-private-run2/audit/1104430f67b74d5cb98979900677588f"
OUT = SITE / "static/data/science.json"
TOPIC_RULES = [
    ("Execution receipts & test results", {"tests", "passed", "failed", "receipt", "inspected"}),
    ("Source handoff & access", {"handoff", "hand off", "join", "access", "authorize", "authorized"}),
    ("Attribution & permissions", {"attribution", "copy", "permission", "attributed", "private"}),
    ("Scope, milestones & acceptance", {"acceptance", "milestone", "scope", "integration", "adapter"}),
    ("Judging & review", {"judge", "review", "usefulness"}),
    ("Field evidence & village use", {"village", "field", "operator", "staff", "reporter"}),
]


def trim(text, words=60):
    w = text.split()
    return " ".join(w[:words]) + (" …" if len(w) > words else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", choices=["names", "codes"], default="names")
    args = ap.parse_args()
    Snap = json.loads(SNAP.read_text())
    names = Snap["names"]
    judge_cfg = {j["name"]: j["remit"] for j in Snap["run_configuration"]["environment"]["judges"]}
    judges = {k for k, v in names.items() if v in judge_cfg}
    host_like = {k for k, v in names.items() if v in ("Project experiment host", "Facilitator NPC")}
    members = [k for k in names if k not in host_like]
    residents = [k for k in members if k not in judges]
    if args.labels == "codes":
        label = {k: (f"J{i + 1}" if k in judges else f"P{i + 1:02d}") for i, k in enumerate(sorted(members))}
    else:
        label = {k: names[k].replace("MosesSamPaul johnraj", "Moses").split()[0].capitalize() for k in members}
    t0 = Snap["started_at"]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out = {"labels_mode": args.labels}

    # ---------------- raw audit pass + active clock ----------------
    reqs, lat, fin, perr, tok = [], [], collections.Counter(), 0, [0, 0]
    errs = []
    for d in sorted(p for p in AUDIT.iterdir() if p.name.isdigit()):
        rq = json.loads((d / "request.json").read_text())
        reqs.append((rq["at"], rq.get("member_id")))
        rp = d / "response.json"
        if not rp.exists():
            fin["missing"] += 1
            continue
        j = json.loads(rp.read_text())
        resp = j.get("response") or {}
        lat.append(j["at"] - rq["at"])
        u = resp.get("usage") or {}
        tok[0] += u.get("prompt_tokens") or 0
        tok[1] += u.get("completion_tokens") or 0
        ch = (resp.get("choices") or [{}])[0]
        fin[ch.get("finish_reason")] += 1
        if ch.get("finish_reason") == "error":
            errs.append(rq["at"])
            continue
        try:
            assert isinstance(json.loads(ch["message"]["content"]), dict)
        except Exception:
            perr += 1
    ra = sorted(t for t, _ in reqs)
    pauses = [(a, b) for a, b in zip(ra, ra[1:]) if b - a > 600]

    def AH(t):
        """active hours since start (global pauses removed)"""
        return (t - t0 - sum(min(b, t) - a for a, b in pauses if a < t)) / 3600

    per_member = collections.defaultdict(list)
    for t, m in reqs:
        per_member[m].append(t)
    lanes = []
    for m in members:
        ts = sorted(per_member.get(m, []))
        end = Snap["cutoff_at"]
        gaps = [[S.r(AH(a), 2), S.r(AH(b), 2)] for a, b in zip(ts, ts[1:] + [end]) if AH(b) - AH(a) > 20 / 60]
        lanes.append({"agent": label[m], "judge": m in judges, "calls": len(ts), "outages": gaps,
                      "outage_h": S.r(sum(b - a for a, b in gaps), 2), "ticks": [S.r(AH(t), 3) for t in ts]})
    usage = con.execute("select status, count(*), sum(input_tokens), sum(output_tokens), sum(cost_usd) from agent_usage group by status").fetchall()
    tf = con.execute("select name, sum(status!='completed'), count(*) from agent_tool_runs group by name order by 3 desc").fetchall()
    read_err = con.execute("select json_extract(result,'$.error'), count(*) from agent_tool_runs where status='failed' and name='project_read' "
                           "group by 1 order by 2 desc").fetchall()
    auto = {x for (x,) in con.execute("select message_id from lab_posts")}
    auto |= {x for (x,) in con.execute("select message_id from workspace_revisions where message_id is not null")}
    auto |= {x for (x,) in con.execute("select message_id from agent_boards where message_id is not null")}
    post_kinds = dict(con.execute("select kind, count(*) from lab_posts group by kind").fetchall())
    allM = sorted(Snap["messages"], key=lambda m: m["created_at"])
    M = [m for m in allM if m["id"] not in auto and m["sender_id"] in label]
    sysm = json.loads((AUDIT / "0001" / "request.json").read_text())["payload"]["messages"][0]["content"]
    aim = re.search(r"This residency experiment studies[^.]*\.", sysm)
    meta = Snap["run_metadata"]
    out["audit"] = {
        "calls": meta["calls"], "completed": meta["completed_calls"], "status": meta["status"],
        "finish": dict(fin), "parse_errors": perr, "provider_errors": fin.get("error", 0),
        "latency_median_s": S.r(np.median(lat), 1), "latency_p90_s": S.r(np.percentile(lat, 90), 1), "latency_max_s": S.r(max(lat), 1),
        "usage_rows": [{"status": s, "rows": n, "in": a, "out": b, "usd": S.r((c or 0) / 1e6, 2)} for s, n, a, b, c in usage],
        "audit_tokens": {"in": tok[0], "out": tok[1]},
        "tool_runs": [{"tool": n, "failed": f, "total": t} for n, f, t in tf],
        "read_errors": [{"error": e, "n": n} for e, n in read_err],
        "messages_total": len(allM), "auto_posts": len(allM) - len([m for m in allM if m["id"] not in auto]),
        "post_kinds": post_kinds, "pauses_h": S.r(sum(b - a for a, b in pauses) / 3600, 2), "n_pauses": len(pauses),
        "active_h": S.r(AH(Snap["cutoff_at"]), 2), "lanes": lanes,
        "calls_range_others": [min(x["calls"] for x in lanes if x["calls"] > 150), max(x["calls"] for x in lanes)],
        "disclosed_aim": aim.group(0) if aim else None,
        "prompt_chars": len(sysm),
    }

    # ---------------- shared structures ----------------
    owner = {p["id"]: p["author"] for p in Snap["projects"]}
    proj_title = {p["id"]: p["title"] for p in Snap["projects"]}
    proj_room = {p["id"]: (p.get("visibility") or {}).get("room_id") for p in Snap["projects"]}
    runs = sorted([r for p in Snap["projects"] for r in p["runs"]], key=lambda r: r["created_at"])
    seen_cmds, self_pass, rows = collections.defaultdict(set), set(), []
    for r in runs:
        x = parse_run(r["result"])
        if x is None:
            continue
        pid = r["project_id"]
        is_self = r["author"] == owner[pid]
        kind = "self" if is_self else ("peer-replication" if x["cmd"] in seen_cmds[pid] else "peer-new-probe")
        rows.append({**x, "kind": kind, "pid": pid, "at": r["created_at"], "rev": r["revision"], "author": r["author"],
                     "judge": r["author"] in judges, "after_pass": (pid, r["revision"]) in self_pass})
        seen_cmds[pid].add(x["cmd"])
        if is_self and x["ok"]:
            self_pass.add((pid, r["revision"]))
    tests = []

    def add(tid, claim, test, stat, p, n, effect=None, ci=None, note=None):
        tests.append({"id": tid, "claim": claim, "test": test, "stat": stat, "p": p, "n": n, "effect": effect, "ci": ci, "note": note})

    # P1 replication vs new probe
    rep = [x for x in rows if x["kind"] == "peer-replication"]
    new = [x for x in rows if x["kind"] == "peer-new-probe"]
    fr = lambda xs: sum(not x["ok"] for x in xs)
    f1 = S.fisher(fr(new), len(new) - fr(new), fr(rep), len(rep) - fr(rep))
    peer = rep + new
    pids = sorted({x["pid"] for x in peer})
    byp = {p: [x for x in peer if x["pid"] == p] for p in pids}

    def diff(ix):
        xs = [x for i in ix for x in byp[pids[i]]]
        a = [x for x in xs if x["kind"] == "peer-new-probe"]
        b = [x for x in xs if x["kind"] == "peer-replication"]
        return (fr(a) / len(a) - fr(b) / len(b)) if a and b else None
    dci = S.boot(diff, len(pids), 3000)
    add("P1", "Peer checks that run a new command find more failures than re-runs of an existing command",
        "Fisher exact; cluster bootstrap over projects for the risk difference",
        f"{fr(new)}/{len(new)} ({fr(new) / len(new):.1%}) vs {fr(rep)}/{len(rep)} ({fr(rep) / len(rep):.1%}); OR {f1['or']:.1f}; "
        f"difference {fr(new) / len(new) - fr(rep) / len(rep):+.1%} (95% CI {dci[0]:+.1%} to {dci[1]:+.1%})",
        f1["p"], len(peer), effect=S.r(f1["or"]), ci=[S.r(x) for x in f1["or_ci"]],
        note=f"{len(pids)} projects; resampling whole projects keeps repeated runs on one project together.")
    after = [x for x in peer if x["after_pass"]]
    add("P2", "Peer runs on a revision the builder already passed rarely fail", "Wilson 95% CI",
        f"{fr(after)} of {len(after)} failed ({fr(after) / len(after):.1%}); {sum((not x['ok']) and x['missing'] for x in after)} of those were missing files",
        None, len(after), effect=S.r(fr(after) / len(after)), ci=[S.r(x) for x in S.wilson(fr(after), len(after))])

    # P3 judges vs residents, stratified by kind
    jt = [x for x in peer if x["judge"]]
    rt = [x for x in peer if not x["judge"]]
    f3 = S.fisher(fr(rt), len(rt) - fr(rt), fr(jt), len(jt) - fr(jt))
    tabs = []
    for k in ("peer-replication", "peer-new-probe"):
        a = [x for x in rt if x["kind"] == k]
        b = [x for x in jt if x["kind"] == k]
        tabs.append(np.array([[fr(a) + .5, len(a) - fr(a) + .5], [fr(b) + .5, len(b) - fr(b) + .5]]))
    st_ = StratifiedTable(tabs)
    mh = st_.test_null_odds()
    add("P3", "Residents' peer checks fail more often than judges'", "Fisher exact (crude) and Mantel–Haenszel stratified by check type",
        f"crude OR {f3['or']:.2f} (p = {f3['p']:.3f}); within check type, pooled OR {st_.oddsratio_pooled:.2f} (95% CI {st_.oddsratio_pooled_confint()[0]:.2f}–{st_.oddsratio_pooled_confint()[1]:.2f})",
        float(mh.pvalue), len(peer), effect=S.r(st_.oddsratio_pooled), ci=[S.r(x) for x in st_.oddsratio_pooled_confint()],
        note="Residents wrote new probes far more often than judges; the stratified estimate asks whether role matters once that is held fixed.")
    out["verify_by_role_kind"] = [{"role": role, "kind": k, "n": len(xs), "fail": fr(xs)}
                                  for role, grp in (("Judges", jt), ("Residents", rt))
                                  for k in ("peer-replication", "peer-new-probe") for xs in [[x for x in grp if x["kind"] == k]]]

    # P4 review decision -> revision, with a matched-time null
    revt = {p["id"]: sorted(rv["created_at"] for rv in p["revisions"]) for p in Snap["projects"]}
    life = {p["id"]: (p["created_at"], max([p["created_at"]] + [rv["created_at"] for rv in p["revisions"]] + [r["created_at"] for r in p["runs"]])) for p in Snap["projects"]}
    WIN = 30 * 60

    def revised_within(pid, t):
        return any(t < x <= t + WIN for x in revt[pid])
    rv_out = collections.defaultdict(lambda: [0, 0])
    curves = collections.defaultdict(list)
    for rv in Snap["reviews"]:
        rv_out[rv["decision"]][0] += 1
        rv_out[rv["decision"]][1] += revised_within(rv["project_id"], rv["created_at"])
        nxt = [x for x in revt[rv["project_id"]] if x > rv["created_at"]]
        curves[rv["decision"]].append((AH(nxt[0]) - AH(rv["created_at"])) * 60 if nxt else None)
    null_hits, null_n = 0, 0
    reviewed = [rv["project_id"] for rv in Snap["reviews"]]
    for _ in range(40):
        for pid in reviewed:
            a, b = life[pid]
            t = S.RNG.uniform(a, max(a + 1, b))
            null_n += 1
            null_hits += revised_within(pid, t)
    cr, ne = rv_out["changes_requested"], rv_out["needs_evidence"]
    f4 = S.fisher(cr[1], cr[0] - cr[1], ne[1], ne[0] - ne[1])
    add("P4", "Specific change requests are acted on more often than requests for more evidence",
        "Fisher exact on revision within 30 min of the review",
        f"changes requested {cr[1]}/{cr[0]} vs needs evidence {ne[1]}/{ne[0]}; random times on the same projects {null_hits / null_n:.0%}",
        f4["p"], cr[0] + ne[0], effect=S.r(f4["or"]), ci=[S.r(x) for x in f4["or_ci"]],
        note="Null: 40 uniformly random time points per reviewed project, drawn within that project's active lifetime.")
    nb = S.wilson(null_hits, null_n)
    out["review_response"] = {
        "window_min": 30,
        "rows": [{"decision": d, "n": v[0], "revised": v[1], "ci": [S.r(x) for x in S.wilson(v[1], v[0])]} for d, v in rv_out.items()]
        + [{"decision": "random_time", "n": null_n, "revised": null_hits, "ci": [S.r(x) for x in nb]}],
        "curves": {d: sorted(x for x in v if x is not None) for d, v in curves.items()},
        "curve_n": {d: len(v) for d, v in curves.items()},
    }

    # Room record (agent-written messages only)
    byroom = collections.defaultdict(list)
    for m in M:
        byroom[m["conversation_id"]].append(m)
    size = {r: len({m["sender_id"] for m in ms}) for r, ms in byroom.items()}
    rs = collections.Counter()
    rr = collections.Counter()
    for r, ms in byroom.items():
        rs[size[r]] += len(ms)
        rr[size[r]] += 1
    out["room_sizes"] = [{"size": k, "rooms": rr[k], "messages": rs[k]} for k in sorted(rs)]

    # ---------------- division of work ----------------
    msgs = collections.Counter(m["sender_id"] for m in M)
    own_rev = collections.Counter()
    oth_rev = collections.Counter()
    for p in Snap["projects"]:
        for rv in p["revisions"]:
            (own_rev if rv["author"] == p["author"] else oth_rev)[rv["author"]] += 1
    self_run = collections.Counter(x["author"] for x in rows if x["kind"] == "self")
    peer_run = collections.Counter(x["author"] for x in peer)
    reviews = collections.Counter(rv["judge"] for rv in Snap["reviews"])
    reads = collections.Counter(o for (o,) in con.execute("select owner_id from agent_tool_runs where name='project_read'"))
    roles = ["Build own", "Build others'", "Test own", "Test others'", "Talk", "Review"]
    prof = []
    for a in members:
        v = [own_rev[a], oth_rev[a], self_run[a], peer_run[a], msgs[a], reviews[a]]
        prof.append((a, v))
    Mx = np.array([v for _, v in prof], float)
    share = Mx / np.maximum(Mx.sum(1, keepdims=True), 1)
    colmean = share[[k for k, (a, _) in enumerate(prof) if a not in judges]].mean(0)
    H_ = -(np.where(share > 0, share * np.log(np.where(share > 0, share, 1)), 0)).sum(1) / np.log(len(roles))
    arche = []
    for k, (a, v) in enumerate(prof):
        if a in judges:
            arche.append("Judge")
            continue
        lift = share[k, :5] / np.maximum(colmean[:5], 1e-9)
        top = int(np.argmax(lift))
        arche.append({0: "Builder", 1: "Contributor", 2: "Builder", 3: "Tester", 4: "Talker"}[top])
    out["division"] = {
        "roles": roles,
        "agents": sorted([{"agent": label[a], "judge": a in judges, "counts": v, "share": [S.r(x) for x in share[k]],
                           "specialisation": S.r(1 - H_[k]), "archetype": arche[k], "reads": reads[a], "calls": len(per_member.get(a, []))}
                          for k, (a, v) in enumerate(prof)], key=lambda r: (r["judge"], r["archetype"], -sum(r["counts"][:4]))),
        "archetype_counts": collections.Counter(arche),
    }
    # concentration: Lorenz + Gini on residents
    res_idx = [k for k, (a, _) in enumerate(prof) if a not in judges]
    lor = {}
    gin = {}
    for j, nm in [(0, "Own-project revisions"), (3, "Peer test runs"), (4, "Messages")]:
        v = Mx[res_idx, j] if j != 0 else Mx[res_idx, 0] + Mx[res_idx, 1]
        nm = "Revisions (all)" if j == 0 else nm
        xs = np.sort(v)
        cum = np.concatenate([[0], np.cumsum(xs) / xs.sum()])
        lor[nm] = [[S.r(i / len(xs)), S.r(c)] for i, c in enumerate(cum)]
        gin[nm] = (S.gini(v), S.boot(lambda ix, v=v: S.gini(v[ix]), len(v)))
    out["division"]["lorenz"] = lor
    out["division"]["gini"] = {k: {"g": S.r(a), "ci": [S.r(x) for x in b]} for k, (a, b) in gin.items()}
    vr, vm = Mx[res_idx, 0] + Mx[res_idx, 1], Mx[res_idx, 4]
    gd = S.boot(lambda ix: S.gini(vr[ix]) - S.gini(vm[ix]), len(vr))
    add("P6", "Building is more concentrated than talking", "Difference in Gini (revisions − messages), agent bootstrap",
        f"Gini {S.gini(vr):.2f} vs {S.gini(vm):.2f}; difference {S.gini(vr) - S.gini(vm):+.2f} (95% CI {gd[0]:+.2f} to {gd[1]:+.2f})",
        None, len(vr), effect=S.r(S.gini(vr) - S.gini(vm)), ci=[S.r(x) for x in gd])
    # per-project contributors
    pc = []
    for p in Snap["projects"]:
        if not p["revisions"]:
            continue
        builders = {rv["author"] for rv in p["revisions"]}
        testers = {r["author"] for r in p["runs"] if r["author"] != p["author"]}
        own_share = sum(rv["author"] == p["author"] for rv in p["revisions"]) / len(p["revisions"])
        pc.append({"title": p["title"], "revisions": len(p["revisions"]), "builders": len(builders), "peer_testers": len(testers - judges),
                   "judge_testers": len(testers & judges), "owner_share": S.r(own_share)})
    solo = sum(1 for x in pc if x["builders"] == 1)
    out["division"]["projects"] = sorted(pc, key=lambda x: -x["revisions"])
    out["division"]["solo_built"] = solo
    out["division"]["with_source"] = len(pc)
    out["division"]["builders_hist"] = collections.Counter(x["builders"] for x in pc)
    out["division"]["peer_tested"] = sum(1 for x in pc if x["peer_testers"] > 0)
    # tester -> owner network among residents, reciprocity vs null
    E = collections.Counter((x["author"], owner[x["pid"]]) for x in peer if x["author"] in residents and owner[x["pid"]] in residents)
    edges = set(E)
    recip = sum(1 for a, b in edges if (b, a) in edges) / max(1, len(edges))
    outs = collections.Counter(a for a, _ in edges)
    ins = collections.Counter(b for _, b in edges)
    sims = []
    nodes = sorted(set(outs) | set(ins))
    for _ in range(2000):
        stubs_o = [a for a in nodes for _ in range(outs[a])]
        stubs_i = list(S.RNG.permutation([b for b in nodes for _ in range(ins[b])]))
        es = {(a, b) for a, b in zip(stubs_o, stubs_i) if a != b}
        sims.append(sum(1 for a, b in es if (b, a) in es) / max(1, len(es)))
    sims = np.array(sims)
    add("P7", "Agents test the work of those who test theirs (reciprocal testing)", "Directed-configuration null (2,000 draws), resident tester → owner edges",
        f"reciprocity {recip:.2f} vs {sims.mean():.2f} expected (null 95% range {np.percentile(sims, 2.5):.2f}–{np.percentile(sims, 97.5):.2f})",
        float((np.sum(sims >= recip) + 1) / (len(sims) + 1)), len(edges), effect=S.r(recip))
    out["division"]["test_edges"] = [{"tester": label[a], "owner": label[b], "runs": n} for (a, b), n in E.most_common()]

    # P8 talk vs build, agent-written messages
    revc = collections.Counter(rv["author"] for p in Snap["projects"] for rv in p["revisions"])
    sc = S.spearman_ci([msgs[a] for a in residents], [revc[a] for a in residents])
    add("P8", "Agents who talk more also build more", "Spearman with agent bootstrap (agent-written messages vs revisions)",
        f"ρ = {sc['rho']:.2f} (95% CI {sc['ci'][0]:.2f}–{sc['ci'][1]:.2f})", sc["p"], len(residents), effect=S.r(sc["rho"]), ci=[S.r(x) for x in sc["ci"]],
        note="Every resident got ≈ 275 model calls (round-robin scheduler) except one whose worker stopped, so this is a trade-off inside a fixed budget, not a difference in activity.")
    out["talk_build"] = [{"agent": label[a], "messages": msgs[a], "revisions": revc[a], "peer_runs": peer_run[a], "reads": reads[a],
                          "archetype": arche[[p[0] for p in prof].index(a)]} for a in residents]

    # P9 premature reads: requests for unpublished source, trend over active time
    pr = con.execute("select created_at, status, json_extract(result,'$.error') from agent_tool_runs where name='project_read'").fetchall()
    hb = collections.defaultdict(lambda: [0, 0])
    for t, stt, e in pr:
        b = int(AH(t))
        hb[b][0] += 1
        hb[b][1] += (stt == "failed" and e and e.startswith("Publish source"))
    hk = sorted(hb)
    ca = S.cochran_armitage([hb[b][1] for b in hk], [hb[b][0] for b in hk], hk)
    out["premature_reads"] = [{"h": b, "n": hb[b][0], "unpublished": hb[b][1], "share": S.r(hb[b][1] / hb[b][0])} for b in hk]
    add("P9", "Requests to read unpublished source decline as the run goes on", "Cochran–Armitage trend in the share of reads refused for unpublished source, by active hour",
        f"{sum(v[1] for v in hb.values())} refusals in {len(pr):,} reads; trend z = {ca['z']:.2f}", ca["p"], len(pr), effect=S.r(ca["z"]))

    # ---------------- directions ----------------
    pa = sorted(Snap["projects"], key=lambda p: p["created_at"])
    first_rev = {p["id"]: min([rv["created_at"] for rv in p["revisions"]], default=None) for p in pa}
    ex = collections.defaultdict(lambda: {"new_projects": 0, "revisions_new": 0, "revisions_old": 0})
    for p in pa:
        ex[int(AH(p["created_at"]) * 2)]["new_projects"] += 1
        for rv in p["revisions"]:
            age = (AH(rv["created_at"]) - AH(p["created_at"]))
            ex[int(AH(rv["created_at"]) * 2)]["revisions_new" if age < 0.5 else "revisions_old"] += 1
    out["explore"] = [{"h": b / 2, **v} for b, v in sorted(ex.items())]
    eh = sorted(ex)
    ca2 = S.cochran_armitage([ex[b]["revisions_new"] for b in eh], [ex[b]["revisions_new"] + ex[b]["revisions_old"] for b in eh], eh)
    add("P11", "Work shifts from starting projects to improving existing ones", "Cochran–Armitage trend in the share of revisions made to projects < 30 min old",
        f"z = {ca2['z']:.2f}", ca2["p"], sum(ex[b]["revisions_new"] + ex[b]["revisions_old"] for b in eh), effect=S.r(ca2["z"]))
    try:
        fam = json.loads(FAMILIES.read_text())
        out["families"] = [{"key": f["key"], "title": f["title"], "status": f["status"],
                            "projects": len(f["project_ids"]) if isinstance(f["project_ids"], list) else None,
                            "people": len(f["resident_names"]) if isinstance(f["resident_names"], list) else None} for f in fam["families"]]
    except Exception as e:  # noqa: BLE001
        out["families_error"] = str(e)
    # message topics over active time (agent-written)
    stop = set("""i you we it this that the a an and or but to of in on for with is are be was were as at by from your my our their
    they he she his her its not no so if then than can could would should will just also more very what which who how when where there here
    one two about into out up do does did have has had me us them some any all each other such only own same too don now get like make made
    i'm you're it's that's we're i'd i'll you'd project revision""".split())
    name_tok = {w.lower() for v in names.values() for w in re.findall(r"[A-Za-z]+", v)}
    vec = TfidfVectorizer(max_df=0.3, min_df=6, stop_words=list(stop | name_tok), ngram_range=(1, 2), sublinear_tf=True,
                          token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z\-]{2,}\b")
    X = vec.fit_transform([m["body"] for m in M])
    nmf = NMF(8, random_state=1, init="nndsvda", max_iter=800)
    W = nmf.fit_transform(X)
    terms = np.array(vec.get_feature_names_out())
    raw_top = [list(terms[c.argsort()[::-1][:10]]) for c in nmf.components_]
    out["topics_raw"] = raw_top
    rules = [("Integration & interfaces", {"adapter", "integration", "interface"}),
             ("Requests to hand off source", {"hand off", "exact source", "please hand"}),
             ("Attribution & permission to copy", {"attribution", "review copy", "may copy"}),
             ("Authorising releases & history", {"authorize", "authorize copying", "public release"}),
             ("Human evidence & instructions", {"human", "reader", "instructions"}),
             ("Failures & packaging defects", {"failed", "failure", "packaging"}),
             ("Independent passes & receipts", {"passed", "independent", "suite"}),
             ("Judge scope & village usefulness", {"judge", "disclosed judge", "village"})]
    lab_t = [next((n for n, kw in rules if kw & set(top)), "Other") for top in raw_top]
    Wn = W / np.maximum(W.sum(1, keepdims=True), 1e-9)
    dom = Wn.argmax(1)
    has = W.sum(1) > 1e-6
    hb2 = np.array([int(AH(m["created_at"])) for m in M])
    ser = []
    for j, n in enumerate(lab_t):
        pts = [[b, S.r(((dom == j) & has & (hb2 == b)).sum() / max(1, (has & (hb2 == b)).sum()))] for b in range(hb2.max() + 1)]
        ser.append({"topic": n, "share": S.r(((dom == j) & has).sum() / has.sum()), "terms": [t for t in raw_top[j] if " " not in t][:6], "points": pts})
    ser.sort(key=lambda x: -x["share"])
    out["topics"] = {"series": ser, "method": "TF-IDF + NMF (k = 8, seed 1) over agent-written messages, labelled by keyword rules"}
    # byte-identical revisions
    dup, tot_rev = 0, 0
    dup_by = collections.Counter()
    for p in Snap["projects"]:
        prev = None
        for rv in sorted(p["revisions"], key=lambda r: int(r["revision"])):
            tot_rev += 1
            if prev is not None and rv["source_hash"] == prev:
                dup += 1
                dup_by[p["id"]] += 1
            prev = rv["source_hash"]
    out["duplicate_revisions"] = {"dup": dup, "total": tot_rev, "projects": len(dup_by)}
    add("P12", "Some 'revisions' change nothing", "Share of revisions byte-identical to the previous revision (Wilson CI)",
        f"{dup} of {tot_rev} revisions ({dup / tot_rev:.0%}) across {len(dup_by)} projects", None, tot_rev,
        effect=S.r(dup / tot_rev), ci=[S.r(x) for x in S.wilson(dup, tot_rev)])

    # ---------------- conversations ----------------
    def turns_of(room, idx):
        ms = byroom[room]
        return [{"who": label[ms[k]["sender_id"]], "seq": k + 1, "h": S.r(AH(ms[k]["created_at"]), 2), "text": trim(ms[k]["body"])} for k in idx]
    cards = []
    # (a) a peer new probe that failed, followed by an owner revision that passed
    cand = []
    for x in new:
        if x["ok"] or x["judge"] or x["missing"]:
            continue
        later = [y for y in rows if y["pid"] == x["pid"] and y["at"] > x["at"] and y["ok"] and int(y["rev"]) > int(x["rev"])]
        if later:
            cand.append((later[0]["at"] - x["at"], x, later[0]))
    cand.sort(key=lambda c: c[0])
    for dt, x, y in cand[:12]:
        room = proj_room.get(x["pid"])
        if room in byroom:
            ms = byroom[room]
            near = [k for k, m in enumerate(ms) if x["at"] - 600 <= m["created_at"] <= y["at"] + 600][:5]
            if len(near) >= 3:
                cards.append({"kind": "probe", "project": proj_title[x["pid"]], "people": sorted({label[ms[k]["sender_id"]] for k in near}),
                              "why": f"{label[x['author']]} wrote a new check on {label[owner[x['pid']]]}'s project; it failed, and a passing revision followed {dt / 60:.0f} min later."
                                     + (" The failure was a packaging defect: the documented command collected no tests, because files were missing." if x["passed"] == 0 and x["failed"] == 0 else ""),
                              "criterion": "resident new probe failed → later revision passed; fastest such case with room talk",
                              "run": {"cmd": x["cmd"][:120], "failed": x["failed"], "passed": x["passed"]}, "turns": turns_of(room, near)})
                break
    # (b) fastest changes_requested -> revision with talk in between
    crs = sorted([rv for rv in Snap["reviews"] if rv["decision"] == "changes_requested"],
                 key=lambda rv: min([t for t in revt[rv["project_id"]] if t > rv["created_at"]], default=9e18) - rv["created_at"])
    for rv in crs[:6]:
        room = proj_room.get(rv["project_id"])
        if room in byroom:
            ms = byroom[room]
            nxt = min([t for t in revt[rv["project_id"]] if t > rv["created_at"]], default=None)
            near = [k for k, m in enumerate(ms) if rv["created_at"] - 120 <= m["created_at"] <= (nxt or rv["created_at"]) + 900][:4]
            if len(near) >= 2:
                cards.append({"kind": "review", "project": proj_title[rv["project_id"]], "people": sorted({label[ms[k]["sender_id"]] for k in near} | {label[rv["judge"]]}),
                              "why": f"Judge {label[rv['judge']]} requested a specific change and a revision followed {((nxt - rv['created_at']) / 60) if nxt else float('nan'):.0f} min later, "
                                     f"but {dup_by.get(rv['project_id'], 0)} of the project's revisions were byte-identical to the one before: the same placeholder kept failing collection.",
                              "criterion": "changes requested → fastest revision with room talk",
                              "review": {"judge": label[rv["judge"]], "decision": rv["decision"], "feedback": trim(rv["feedback"], 70)},
                              "turns": turns_of(room, near)})
                break
    # (c) largest active room
    biggest = max(byroom, key=lambda r: (size[r], len(byroom[r])))
    ms = byroom[biggest]
    cards.append({"kind": "team", "project": None, "people": sorted({label[m["sender_id"]] for m in ms}),
                  "why": f"The largest working room: {size[biggest]} agents, {len(ms)} agent-written messages.",
                  "criterion": "max active members, then max messages", "turns": turns_of(biggest, sorted({0, 1, len(ms) // 2, len(ms) - 1}))})
    # (d) handoff friction: room with most requests for source handoff
    HAND = re.compile(r"hand ?off|handoff|exact source|publish (the )?source", re.I)
    hf = {r: sum(bool(HAND.search(m["body"])) for m in ms) for r, ms in byroom.items()}
    hr = max(hf, key=hf.get)
    ms = byroom[hr]
    ix = [k for k, m in enumerate(ms) if HAND.search(m["body"])][:4]
    cards.append({"kind": "friction", "project": None, "people": sorted({label[m["sender_id"]] for m in ms}),
                  "why": f"The room with the most talk about handing over or publishing source ({hf[hr]} of {len(ms)} messages).",
                  "criterion": "max messages matching handoff/publish-source", "turns": turns_of(hr, ix)})
    # (e) disagreement: highest share of pushback in rooms with >= 12 messages
    PUSH = re.compile(r"(\bi (disagree|object)\b|\bdisagree|not convinced|push back|i['’]d resist|i don['’]t think|i['’]m not sure|\bi decline|\bdeclin(e|ing) (the|your|to)|i won['’]t|won['’]t accept|not accept)", re.I)
    pr_ = {r: np.mean([bool(PUSH.search(m["body"])) for m in ms]) for r, ms in byroom.items() if len(ms) >= 12}
    dr = max(pr_, key=pr_.get)
    ms = byroom[dr]
    hits = [k for k, m in enumerate(ms) if PUSH.search(m["body"])][:2]
    ix = sorted(set([0] + [j for k in hits for j in (k - 1, k) if j >= 0]))[:5]
    cards.append({"kind": "dispute", "project": None, "people": sorted({label[m["sender_id"]] for m in ms}),
                  "why": f"Highest share of disagreement or refusal among rooms with ≥ 12 messages ({pr_[dr]:.0%} of turns). The pushback is technical: "
                         "a statistical assumption is challenged, the correction is accepted, and the critique is credited in the documentation.",
                  "criterion": "max pushback share", "turns": turns_of(dr, ix)})
    out["conversations"] = cards

    ps = [t["p"] for t in tests if t["p"] is not None]
    adj = iter(S.bh(ps))
    for t in tests:
        t["p_bh"] = next(adj) if t["p"] is not None else None
    out["tests"] = tests
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"), default=float))
    print("wrote", OUT, OUT.stat().st_size)
    for t in tests:
        print(t["id"], t["claim"], "|", t["stat"], "| p", t["p"], "bh", t["p_bh"])
    a = out["audit"]
    print({k: a[k] for k in a if k not in ("lanes",)})
    print([(x["agent"], x["calls"], x["outages"]) for x in a["lanes"] if x["outages"]])
    print(out["division"]["archetype_counts"], out["division"]["gini"], "solo", solo, "/", len(pc), "peer tested", out["division"]["peer_tested"])
    print(out["review_response"]["rows"])
    print("topics", raw_top)
    print(out["explore"])
    for c in cards:
        print("\n##", c["kind"], c["why"], c["people"], c.get("project"))
        for t in c["turns"]:
            print("  ", t["who"], t["seq"], t["text"][:170])


if __name__ == "__main__":
    main()
