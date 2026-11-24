"""Build the project-team study's figure data from the frozen project snapshot.

Reads (never writes) the parent workspace's frozen project-completion snapshot,
the retrospective family classifications, the networking archive (for the
cross-setting comparison) and the run database (usage only). Writes
static/data/projects.json. No resident code is executed.

Usage:  python analysis/build_data.py [--labels names|codes]
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import statistics as st
from pathlib import Path

import networkx as nx
import numpy as np
from scipy.stats import spearmanr

SITE = Path(__file__).resolve().parents[1]
WS = SITE.parents[1]
SNAP = WS / "residency_app/experiments/project-completion/evaluations/final-snapshot.json"
FAMILIES = WS / "sites/residency-findings/dist/data/final.json"
ARCHIVE = WS / "sites/zugrama-residency-stories/dist/archive.json"
DB = WS / "residency_app/.data/project-completion-private-run2/state/residency.sqlite3"
OUT = SITE / "static/data/projects.json"

READ_TOOLS = {"project_read", "workspace_read", "conversation_recall", "project_receipt", "board_read", "village_read"}
WRITE_TOOLS = {"project_write", "project_create", "project_artifact", "project_handoff", "project_share",
               "workspace_update", "workspace_create", "board_add"}
EXEC_TOOLS = {"project_run", "python_run", "village_verify"}
WEB_TOOLS = {"web_read", "web_search"}
REVIEW_TOOLS = {"judge_review"}


def category(name):
    for cat, names in [("Read state", READ_TOOLS), ("Write / publish", WRITE_TOOLS), ("Execute", EXEC_TOOLS),
                       ("Web", WEB_TOOLS), ("Judge review", REVIEW_TOOLS)]:
        if name in names:
            return cat
    return "Other"


def r3(x):
    return round(float(x), 3)


def parse_run(result):
    try:
        j = json.loads(result)
    except Exception:
        return None
    out = j.get("output") or ""
    counts = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|errors?|skipped)", out)}
    return {
        "ok": bool(j.get("ok")),
        "passed": counts.get("passed", 0),
        "failed": counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0),
        "cmd": " ".join(j.get("command") or []),
        "missing": bool(re.search(r"No such file or directory|ModuleNotFoundError|ImportError", out)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", choices=["names", "codes"], default="names")
    args = ap.parse_args()

    S = json.loads(SNAP.read_text())
    # Receipts the platform posted into chat under an agent's name are not agent talk; drop them.
    _con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    auto = {x for (x,) in _con.execute("select message_id from lab_posts")}
    auto |= {x for (x,) in _con.execute("select message_id from workspace_revisions where message_id is not null")}
    auto |= {x for (x,) in _con.execute("select message_id from agent_boards where message_id is not null")}
    n_all = len(S["messages"])
    S["messages"] = [m for m in S["messages"] if m["id"] not in auto]
    names = S["names"]
    judge_cfg = {j["name"]: j["remit"] for j in S["run_configuration"]["environment"]["judges"]}
    judge_ids = {k for k, v in names.items() if v in judge_cfg}
    judge_remit = {k: judge_cfg[names[k]] for k in judge_ids}
    host_like = {k for k, v in names.items() if v in ("Project experiment host", "Facilitator NPC")}
    members = [k for k in names if k not in host_like]
    residents = [k for k in members if k not in judge_ids]
    if args.labels == "codes":
        label = {k: (f"J{i + 1}" if k in judge_ids else f"P{i + 1:02d}") for i, k in enumerate(sorted(members))}
    else:
        label = {k: names[k].replace("MosesSamPaul johnraj", "Moses").split()[0].capitalize() for k in members}
    t0, t1 = S["started_at"], S["cutoff_at"]
    owner = {p["id"]: p["author"] for p in S["projects"]}
    title = {p["id"]: p["title"] for p in S["projects"]}
    out = {"labels_mode": args.labels, "auto_posts_excluded": n_all - len(S["messages"])}

    # ---------- overview ----------
    meta = S["run_metadata"]
    tb = meta["time_budget"]
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    usd, tin, tout = con.execute("select sum(cost_usd), sum(input_tokens), sum(output_tokens) from agent_usage").fetchone()
    cost_by = dict(con.execute("select owner_id, sum(cost_usd) from agent_usage group by owner_id").fetchall())
    out["overview"] = {
        "residents": len(residents), "judges": len(judge_ids), "model": meta["model"],
        "reasoning": meta["reasoning_effort"], "messages": len(S["messages"]),
        "projects": len(S["projects"]), "revisions": sum(len(p["revisions"]) for p in S["projects"]),
        "executions": sum(len(p["runs"]) for p in S["projects"]), "reviews": len(S["reviews"]),
        "tool_calls": len(S["tools"]), "model_calls": meta["calls"],
        "active_hours": r3(tb["elapsed_active_seconds"] / 3600), "paused_hours": r3(tb["paused_seconds"] / 3600),
        "wall_hours": r3((t1 - t0) / 3600), "usd": round(usd / 1e6, 2), "input_tokens": tin, "output_tokens": tout,
    }

    # ---------- rooms / team structure ----------
    byroom = collections.defaultdict(list)
    for m in sorted(S["messages"], key=lambda m: m["created_at"]):
        byroom[m["conversation_id"]].append(m)
    active = {r: {m["sender_id"] for m in ms if m["sender_id"] in label} for r, ms in byroom.items()}
    size_rooms = collections.Counter(len(a) for a in active.values())
    size_msgs = collections.Counter()
    for r, ms in byroom.items():
        size_msgs[len(active[r])] += len(ms)
    out["room_sizes"] = [{"size": k, "rooms": size_rooms[k], "messages": size_msgs[k]} for k in sorted(size_rooms)]
    out["rooms_with_judge"] = sum(1 for a in active.values() if a & judge_ids)

    G = nx.Graph()
    G.add_nodes_from(members)
    for r, a in active.items():
        a = sorted(a)
        share = len(byroom[r]) / max(1, len(a) - 1)
        for i in range(len(a)):
            for j in range(i + 1, len(a)):
                w = G.get_edge_data(a[i], a[j], {}).get("weight", 0)
                G.add_edge(a[i], a[j], weight=w + share)
    comm = nx.community.louvain_communities(G, weight="weight", seed=1)
    cid = {n: i for i, c in enumerate(sorted(comm, key=len, reverse=True)) for n in c}
    bc = nx.betweenness_centrality(G)
    Rg = G.subgraph(residents)
    msgs_by = collections.Counter(m["sender_id"] for m in S["messages"])
    out["network"] = {
        "nodes": [{"id": label[n], "judge": n in judge_ids, "community": cid[n], "messages": msgs_by[n],
                   "betweenness": r3(bc[n])} for n in members],
        "edges": [{"source": label[a], "target": label[b], "weight": round(d["weight"], 1)} for a, b, d in G.edges(data=True)],
        "density_all": r3(nx.density(G)), "density_residents": r3(nx.density(Rg)),
        "resident_pairs": Rg.number_of_edges(), "resident_pairs_possible": len(residents) * (len(residents) - 1) // 2,
        "modularity": r3(nx.community.modularity(G, comm, weight="weight")), "communities": len(comm),
        "clustering": r3(nx.average_clustering(G)),
    }
    lat = [b["created_at"] - a["created_at"] for ms in byroom.values() for a, b in zip(ms, ms[1:])
           if a["sender_id"] != b["sender_id"]]
    words = [len(m["body"].split()) for m in S["messages"]]
    out["talk"] = {"latency_median_s": round(float(np.median(lat))), "words_median": float(np.median(words))}

    # ---------- tool allocation ----------
    per_agent = collections.defaultdict(collections.Counter)
    fails = collections.Counter()
    for t in S["tools"]:
        if t["owner_id"] in label:
            per_agent[t["owner_id"]][category(t["name"])] += 1
        if t["status"] == "failed":
            fails[t["name"]] += 1
    cats = ["Read state", "Write / publish", "Execute", "Web", "Judge review", "Other"]
    tool_totals = collections.Counter(t["name"] for t in S["tools"])
    out["tools"] = {
        "categories": cats,
        "by_agent": [{"agent": label[a], "judge": a in judge_ids, **{c: per_agent[a][c] for c in cats}}
                     for a in sorted(per_agent, key=lambda a: (a in judge_ids, -sum(per_agent[a].values())))],
        "totals": tool_totals.most_common(),
        "category_totals": {c: sum(per_agent[a][c] for a in per_agent) for c in cats},
        "failed": fails.most_common(),
    }
    tl = collections.defaultdict(collections.Counter)
    for t in S["tools"]:
        tl[int((t["created_at"] - t0) // 1800)][category(t["name"])] += 1
    out["tools"]["timeline"] = [{"h": b / 2, **{c: v[c] for c in cats}} for b, v in sorted(tl.items())]

    # ---------- verification ----------
    runs = sorted([r for p in S["projects"] for r in p["runs"]], key=lambda r: r["created_at"])
    seen_cmds = collections.defaultdict(set)
    self_pass = set()
    rows = []
    for r in runs:
        x = parse_run(r["result"])
        if x is None:
            continue
        pid, key = r["project_id"], (r["project_id"], r["revision"])
        is_self = r["author"] == owner[pid]
        kind = "self"
        if not is_self:
            replication = x["cmd"] in seen_cmds[pid]
            after_pass = key in self_pass
            kind = "peer-replication" if replication else "peer-new-probe"
            x["after_self_pass"] = after_pass
        rows.append({"kind": kind, **x, "pid": pid, "at": r["created_at"], "revision": r["revision"],
                     "judge": r["author"] in judge_ids})
        seen_cmds[pid].add(x["cmd"])
        if is_self and x["ok"]:
            self_pass.add(key)
    ver = {}
    for k in ["self", "peer-replication", "peer-new-probe"]:
        xs = [x for x in rows if x["kind"] == k]
        ver[k] = {"n": len(xs), "fail": sum(not x["ok"] for x in xs),
                  "fail_missing": sum((not x["ok"]) and x["missing"] for x in xs)}
    after = [x for x in rows if x["kind"] != "self" and x.get("after_self_pass")]
    ver["peer_after_self_pass"] = {"n": len(after), "fail": sum(not x["ok"] for x in after),
                                   "fail_missing": sum((not x["ok"]) and x["missing"] for x in after),
                                   "replications": sum(x["kind"] == "peer-replication" for x in after)}
    for role, flag in [("peer_by_judges", True), ("peer_by_residents", False)]:
        xs = [x for x in rows if x["kind"] != "self" and x["judge"] == flag]
        ver[role] = {"n": len(xs), "fail": sum(not x["ok"] for x in xs),
                     "new_probes": sum(x["kind"] == "peer-new-probe" for x in xs)}
    firsts = {}
    for x in rows:
        firsts.setdefault((x["pid"], x["revision"]), x)
    ver["first_run_on_revision"] = {"n": len(firsts), "ok": sum(x["ok"] for x in firsts.values())}
    out["verification"] = ver

    # ---------- revisions / lifecycle ----------
    rp = collections.Counter(len(p["revisions"]) for p in S["projects"])
    out["revisions_per_project"] = [{"revisions": k, "projects": rp[k]} for k in sorted(rp)]
    revs = [(p, rv) for p in S["projects"] for rv in p["revisions"]]
    out["revisions_by_non_owner"] = sum(1 for p, rv in revs if rv["author"] != p["author"])
    ttg = []
    for p in S["projects"]:
        ok = [r["created_at"] for r in p["runs"] if (parse_run(r["result"]) or {}).get("ok")]
        if ok:
            ttg.append((min(ok) - p["created_at"]) / 60)
    out["time_to_first_pass_min"] = {"n": len(ttg), "median": round(float(np.median(ttg)), 1),
                                     "values": [round(v, 1) for v in ttg],
                                     "never": sum(1 for p in S["projects"] if p["runs"]) - len(ttg),
                                     "no_runs": sum(1 for p in S["projects"] if not p["runs"])}

    # ---------- judges ----------
    revtimes = {p["id"]: sorted(rv["created_at"] for rv in p["revisions"]) for p in S["projects"]}
    rev_after = collections.defaultdict(lambda: [0, 0])
    lag = collections.defaultdict(list)
    by_judge = collections.defaultdict(collections.Counter)
    for rv in S["reviews"]:
        by_judge[rv["judge"]][rv["decision"]] += 1
        later = [t for t in revtimes[rv["project_id"]] if t > rv["created_at"]]
        rev_after[rv["decision"]][0] += 1
        rev_after[rv["decision"]][1] += bool(later)
        if later:
            lag[rv["decision"]].append((later[0] - rv["created_at"]) / 60)
    decisions = sorted({d for c in by_judge.values() for d in c})
    out["judges"] = {
        "decisions": decisions,
        "by_judge": [{"judge": label[j], "remit": judge_remit[j], **{d: by_judge[j][d] for d in decisions}}
                     for j in sorted(by_judge, key=lambda j: label[j])],
        "followed_by_revision": [{"decision": d, "reviews": rev_after[d][0], "revised": rev_after[d][1],
                                  "median_lag_min": round(float(np.median(lag[d])), 1) if lag[d] else None}
                                 for d in decisions],
        "projects_reviewed": len({rv["project_id"] for rv in S["reviews"]}),
        "feedback_words_median": float(np.median([len(rv["feedback"].split()) for rv in S["reviews"]])),
    }

    # ---------- talk vs build ----------
    revc = collections.Counter(rv["author"] for p, rv in revs)
    runc = collections.Counter(r["author"] for r in runs)
    pts = [{"agent": label[a], "messages": msgs_by[a], "revisions": revc[a], "executions": runc[a],
            "usd": round(cost_by.get(a, 0) / 1e6, 2)} for a in residents]
    out["talk_build"] = {
        "points": pts,
        "rho_msgs_revisions": r3(spearmanr([p["messages"] for p in pts], [p["revisions"] for p in pts]).correlation),
        "rho_msgs_executions": r3(spearmanr([p["messages"] for p in pts], [p["executions"] for p in pts]).correlation),
        "judges": [{"agent": label[j], "messages": msgs_by[j]} for j in judge_ids],
    }

    # ---------- outcome families (retrospective classification, prior audit) ----------
    try:
        fam = json.loads(FAMILIES.read_text())
        oc = collections.Counter(f["status"] for f in fam["families"])
        out["families"] = [{"outcome": k, "families": v} for k, v in oc.most_common()]
    except Exception as e:  # noqa: BLE001
        out["families_error"] = str(e)

    # ---------- same personas, two settings ----------
    A = json.loads(ARCHIVE.read_text())
    R3 = next(r for r in A["runs"] if r["number"] == 3)
    net_sent = collections.Counter(m["sender_id"] for m in R3["messages"])
    key = lambda s: s.lower().replace("mosessampaul", "moses").split()[0]
    alias = {"louisa": "lou"}
    pmap = {key(v): k for k, v in names.items()}
    cross = []
    for p in A["people"]:
        k = alias.get(key(p["name"]), key(p["name"]))
        if k in pmap and pmap[k] in label:
            cross.append({"agent": label[pmap[k]], "judge": pmap[k] in judge_ids,
                          "networking": net_sent[p["id"]], "projects": msgs_by[pmap[k]]})
    res = [c for c in cross if not c["judge"]]
    rr = spearmanr([c["networking"] for c in res], [c["projects"] for c in res])
    out["cross_setting"] = {"points": cross, "rho": r3(rr.correlation), "p": r3(rr.pvalue), "n": len(res)}

    out["agents"] = [{"agent": label[a], "role": "judge" if a in judge_ids else "resident",
                      "messages": msgs_by[a], "revisions": revc[a], "executions": runc[a],
                      "tool_calls": sum(per_agent[a].values()), "usd": round(cost_by.get(a, 0) / 1e6, 2)}
                     for a in members]
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    print("wrote", OUT, OUT.stat().st_size)
    print(json.dumps({k: out[k] for k in ["overview", "verification", "revisions_by_non_owner"]}, indent=1))
    print(out["judges"]["followed_by_revision"], out.get("families"), out["cross_setting"]["rho"], out["time_to_first_pass_min"]["median"])


if __name__ == "__main__":
    main()
