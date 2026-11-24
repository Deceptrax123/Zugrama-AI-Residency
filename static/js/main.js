/* Figures for Study 2 (project teams). Data: static/data/projects.json + science.json */
(async function () {
  const [D, X] = await Promise.all([
    fetch("static/data/projects.json").then((r) => r.json()),
    fetch("static/data/science.json").then((r) => r.json()),
  ]);
  const C = window.Charts, fmt = C.fmt;
  const $ = (id) => document.getElementById(id);
  const pct = d3.format(".0%"), pct1 = d3.format(".1%");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const pfmt = (p) => (p == null ? "—" : p < 0.001 ? "< 0.001" : p.toFixed(3));
  const T = Object.fromEntries(X.tests.map((t) => [t.id, t]));
  const AU = X.audit, O = D.overview;
  const wilson = (k, n) => { const z = 1.96, p = k / n, d = 1 + z * z / n, c = (p + z * z / (2 * n)) / d, h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d; return [Math.max(0, c - h), Math.min(1, c + h)]; };

  const workUnit = $("work-unit");
  const shareOption = workUnit.querySelector('input[value="share"]');
  const byAuthor = D.team_work.authorship.map((row) => ({ ...row, total: row.outside_run + row.no_outside_run }));
  function renderAuthorship() {
    const byShare = shareOption.checked;
    const chart = $("fig-builders");
    C.bars(chart, {
      data: byAuthor.map((row) => ({ ...row,
        outside: byShare ? row.outside_run / row.total : row.outside_run,
        without: byShare ? row.no_outside_run / row.total : row.no_outside_run,
      })),
      x: "group", keys: ["outside", "without"], stacked: true, colors: ["--s1", "--neutral"],
      yMax: byShare ? 1 : 50, yFormat: byShare ? pct : undefined,
      yLabel: byShare ? "share of entries" : "project entries", height: 220,
      tipFmt: (row) => `<b>${esc(row.group)}</b><br>Outside run: ${row.outside_run} of ${row.total} (${pct(row.outside_run / row.total)})`,
    });
    const [solo, multi] = byAuthor;
    const summary = byShare
      ? `An outside agent ran ${pct(solo.outside_run / solo.total)} of single-author entries and ${pct(multi.outside_run / multi.total)} of multi-author entries.`
      : `An outside agent ran ${solo.outside_run} of the ${solo.total} single-author entries and ${multi.outside_run} of the ${multi.total} multi-author entries.`;
    $("work-reading").textContent = summary;
    chart.querySelector("svg").setAttribute("aria-label", `Authorship and outside execution. ${summary}`);
  }
  workUnit.addEventListener("change", renderAuthorship);
  C.register(renderAuthorship);

  $("run-stats").innerHTML = [
    [fmt(AU.calls), "model calls audited"], [fmt(O.messages), "agent-written messages"], [fmt(O.revisions), "source revisions"],
    [fmt(O.executions), "sandboxed executions"], [fmt(O.reviews), "judge reviews"], ["$" + Math.round(O.usd), "API-equivalent spend"],
  ].map(([v, l]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
  $("aim").textContent = `“${AU.disclosed_aim}”`;
  const sl = (id, t) => { $(id).textContent = `${t.test}: ${t.stat}` + (t.p != null ? `; p ${pfmt(t.p).startsWith("<") ? "" : "= "}${pfmt(t.p)}, BH-adjusted ${pfmt(t.p_bh)}` : ""); };
  sl("sl-p1", T.P1); sl("sl-p3", T.P3); sl("sl-p4", T.P4); sl("sl-p6", T.P6); sl("sl-p11", T.P11);

  // ---------- audit ----------
  const dead = AU.lanes.find((l) => l.outage_h > 2);
  const rec = AU.usage_rows.find((u) => u.status === "recorded");
  const pr = AU.tool_runs.find((t) => t.tool === "project_read"), wr = AU.tool_runs.find((t) => t.tool === "web_read"), pa = AU.tool_runs.find((t) => t.tool === "project_artifact");
  const re = Object.fromEntries(AU.read_errors.map((e) => [e.error, e.n]));
  const items = [
    ["sev-high", "High", "Platform receipts recorded as talk", `${AU.auto_posts} of ${fmt(AU.messages_total)} chat messages (${pct(AU.auto_posts / AU.messages_total)}) were posted by the platform under an agent's name: ${AU.post_kinds.run} execution receipts, ${AU.post_kinds.revision} revision notices, ${AU.post_kinds.review} review notices and ${AU.auto_posts - AU.post_kinds.run - AU.post_kinds.revision - AU.post_kinds.review} workspace posts. They are excluded from all talk measures.`],
    ["sev-high", "High", "A worker stopped", `${dead.agent} stopped at ${dead.outages[0][0].toFixed(1)} active h and made only one later call. Absent for ${dead.outage_h.toFixed(1)} of ${AU.active_h.toFixed(1)} h (${dead.calls} calls vs ${AU.calls_range_others[0]}–${AU.calls_range_others[1]} for everyone else). Worker supervision logged no repair.`],
    ["sev-mid", "Medium", "The hypothesis was in the prompt", `Every one of ${fmt(AU.calls)} system prompts stated the study's aim and told agents to separate drafts from tested and validated work. That plausibly shapes the evidence-heavy talk.`],
    ["sev-mid", "Medium", "Reads of unpublished work", `${fmt(pr.failed)} of ${fmt(pr.total)} project reads failed: ${re["Publish source files before running or reviewing"]} because the source was not yet published, ${re["Source file not found"]} for missing files. Web reads failed ${wr.failed}/${wr.total} (mostly HTTP 403), artifact fetches ${pa.failed}/${pa.total}.`],
    ["sev-ok", "OK", "Ledger reconciles with raw responses", `Raw responses: ${fmt(AU.audit_tokens.in)} input / ${fmt(AU.audit_tokens.out)} output tokens. Ledger: ${fmt(rec.in)} / ${fmt(rec.out)} (exact match).`],
    ["sev-ok", "OK", "Responses are well-formed", `${AU.provider_errors} provider errors and ${AU.parse_errors} unparseable actions in ${fmt(AU.calls)} calls. Median model latency ${AU.latency_median_s} s (p90 ${AU.latency_p90_s} s).`],
  ];
  $("audit-items").innerHTML = items.map(([c, s, h, p]) => `<div class="audit-item ${c}"><span class="sev">${s}</span><h4>${h}</h4><p>${esc(p)}</p></div>`).join("");
  const unk = AU.usage_rows.filter((u) => u.status !== "recorded").reduce((a, u) => a + u.rows, 0);
  $("tbl-audit").innerHTML = `<thead><tr><th>Check</th><th>Value</th><th>Status</th></tr></thead><tbody>${[
    ["Model calls issued / completed", `${fmt(AU.calls)} / ${fmt(AU.completed)}`, `${AU.calls - AU.completed} incomplete`],
    ["Ledger rows recorded / rejected or unknown", `${fmt(rec.rows)} / ${unk}`, `= the ${AU.provider_errors} provider errors`],
    ["Input tokens: raw responses vs ledger", `${fmt(AU.audit_tokens.in)} vs ${fmt(rec.in)}`, "exact match"],
    ["Output tokens: raw responses vs ledger", `${fmt(AU.audit_tokens.out)} vs ${fmt(rec.out)}`, "exact match"],
    ["Chat messages: total / agent-written", `${fmt(AU.messages_total)} / ${fmt(AU.messages_total - AU.auto_posts)}`, "receipts excluded"],
    ["Active hours", AU.active_h.toFixed(2), "active clock"],
    ["Spend (API-equivalent)", "$" + rec.usd.toFixed(2), "—"],
  ].map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody>`;

  // ---------- conversations ----------
  const kindName = { probe: "A peer probe that found a defect", review: "A fast response that fixed nothing", team: "The largest team", friction: "Handing source over", dispute: "Disagreement, then concession" };
  $("convos").innerHTML = X.conversations.map((c, i) => {
    let prev = 0;
    const turns = c.turns.map((t) => {
      const gap = t.seq - prev > 1 && prev > 0 ? `<div class="turn gap">… ${t.seq - prev - 1} message${t.seq - prev - 1 > 1 ? "s" : ""} omitted …</div>` : "";
      prev = t.seq;
      return `${gap}<div class="turn"><div class="who">${esc(t.who)}<span>msg ${t.seq} · ${t.h.toFixed(2)} h</span></div><q>${esc(t.text)}</q></div>`;
    }).join("");
    const fb = c.review ? `<div class="feedback"><b>${esc(c.review.judge)}'s review (${esc(c.review.decision.replace("_", " "))}):</b> ${esc(c.review.feedback)}</div>` : "";
    const run = c.run ? `<div class="stat-line" style="margin:0 0 8px">failed probe: ${esc(c.run.cmd)}</div>` : "";
    return `<article class="convo"><header><h4>${i + 1}. ${esc(kindName[c.kind] || c.kind)}</h4><span class="meta">${esc(c.people.join(", "))}${c.project ? " · " + esc(c.project) : ""}</span></header>
      <p class="why">${esc(c.why)}</p>${fb}${run}${turns}<p class="crit">Selection rule: ${esc(c.criterion)}</p></article>`;
  }).join("");

  // ---------- tests ----------
  const verdict = (t) => {
    if (t.id === "P1") return ["weak", "Significant, not cluster-robust"];
    if (t.p == null) return ["est", "Estimate"];
    return t.p_bh < 0.05 ? ["yes", "Supported"] : ["no", "Not supported"];
  };
  $("tbl-tests").innerHTML = `<div class="table-wrap"><table class="compare tests"><thead><tr><th>ID</th><th>Hypothesis</th><th>Test</th><th>Result</th><th>p (BH)</th><th>Verdict</th></tr></thead><tbody>${
    X.tests.slice().sort((a, b) => +a.id.slice(1) - +b.id.slice(1)).map((t) => { const [c, v] = verdict(t); return `<tr><td>${t.id}</td><td>${esc(t.claim)}</td><td>${esc(t.test)}</td><td>${esc(t.stat)}${t.note ? `<br><span style="color:var(--muted);font-size:12.5px">${esc(t.note)}</span>` : ""}</td><td>${pfmt(t.p_bh)}</td><td><span class="verdict ${c}">${v}</span></td></tr>`; }).join("")
  }</tbody></table></div>`;

  C.table($("tbl-agents"), {
    rows: D.agents.map((a) => ({ ...a, archetype: (X.division.agents.find((x) => x.agent === a.agent) || {}).archetype || "" })),
    columns: [
      { key: "agent", label: "Agent" }, { key: "archetype", label: "Archetype" }, { key: "messages", label: "Messages" }, { key: "revisions", label: "Revisions" },
      { key: "executions", label: "Executions" }, { key: "tool_calls", label: "Tool calls" }, { key: "usd", label: "Spend ($)", fmt: (v) => v.toFixed(2) },
    ],
  });

  const V = D.verification;
  C.register(() => {
    // Fig 1: network
    const rmax = d3.max(D.network.nodes, (n) => n.messages);
    C.network($("fig-network"), {
      nodes: D.network.nodes, edges: D.network.edges, height: Math.min(520, Math.max(380, $("fig-network").clientWidth * 0.55)),
      colorOf: (d) => (d.judge ? "--s2" : "--s1"), radius: (d) => 4 + 10 * Math.sqrt(d.messages / rmax),
      tipFmt: (d) => `<b>${d.id}</b>${d.judge ? " (judge)" : ""}<br>${fmt(d.messages)} agent-written messages<br>betweenness ${d.betweenness.toFixed(3)}`,
    });

    // Fig 2: lanes
    C.swimlanes($("fig-lanes"), { lanes: AU.lanes.slice().sort((a, b) => (a.judge - b.judge) || (b.calls - a.calls)), xMax: AU.active_h, xLabel: "active hours →", rowH: 14, labelW: 80 });

    // Fig 3: verification forest
    const vr = [
      ["Builder's own runs", V.self], ["Peer: replication", V["peer-replication"]], ["Peer: new probe", V["peer-new-probe"]], ["Peer, after builder passed", V.peer_after_self_pass],
    ].map(([label, o]) => ({ label, est: o.fail / o.n, ci: wilson(o.fail, o.n), ...o }));
    C.forest($("fig-verify"), {
      rows: vr, xDomain: [0, 0.3], xFormat: d3.format(".0%"), xLabel: "share failed →", labelW: 190,
      colorOf: (r) => (r.label.includes("probe") ? "--s2" : "--s1"),
      tipFmt: (r) => `<b>${r.label}</b><br>${r.fail} of ${r.n} failed (${pct1(r.est)})<br>95% CI ${pct1(r.ci[0])}–${pct1(r.ci[1])}<br>${r.fail_missing} were missing files/modules`,
    });
    // Fig 4: by role × kind
    const rk = X.verify_by_role_kind.map((r) => ({ ...r, label: `${r.role} · ${r.kind === "peer-new-probe" ? "new probe" : "replication"}`, est: r.fail / r.n, ci: wilson(r.fail, r.n) }));
    C.forest($("fig-verify-role"), {
      rows: rk, xDomain: [0, 0.4], xFormat: d3.format(".0%"), xLabel: "share failed →", labelW: 190,
      colorOf: (r) => (r.role === "Judges" ? "--s2" : "--s1"),
      tipFmt: (r) => `<b>${r.label}</b><br>${r.fail} of ${r.n} failed (${pct1(r.est)})<br>95% CI ${pct1(r.ci[0])}–${pct1(r.ci[1])}`,
    });

    // Fig 5: review follow-through
    const nice = { needs_evidence: "Needs evidence", changes_requested: "Changes requested", simulation_demo_ready: "Demo ready", random_time: "Random time (baseline)" };
    const rr = X.review_response.rows.filter((r) => r.decision !== "simulation_demo_ready").map((r) => ({ ...r, label: nice[r.decision], est: r.revised / r.n }));
    const base = rr.find((r) => r.decision === "random_time").est;
    C.forest($("fig-follow"), {
      rows: rr, xDomain: [0, 1], ref: base, xFormat: d3.format(".0%"), xLabel: "revised within 30 min →", labelW: 160,
      colorOf: (r) => (r.decision === "changes_requested" ? "--s2" : r.decision === "random_time" ? "--neutral" : "--s1"),
      tipFmt: (r) => `<b>${r.label}</b><br>${fmt(r.revised)} of ${fmt(r.n)} (${pct(r.est)})<br>95% CI ${pct(r.ci[0])}–${pct(r.ci[1])}`,
    });
    const curve = (k) => { const v = X.review_response.curves[k], n = X.review_response.curve_n[k]; return [[0, 0], ...v.map((m, i) => [Math.min(m, 240), (i + 1) / n])]; };
    C.line($("fig-curves"), {
      series: [{ name: "Changes req.", color: "--s2", values: curve("changes_requested"), step: true }, { name: "Needs evid.", color: "--s1", values: curve("needs_evidence") }],
      xMax: 240, yMax: 1, yFormat: d3.format(".0%"), xLabel: "minutes after review →", xFormat: d3.format(".0f"), height: 230,
      markers: [{ x: 30, label: "30 min" }],
    });
    C.hbars($("fig-judges"), {
      data: D.judges.by_judge, label: "judge", keys: ["needs_evidence", "changes_requested", "simulation_demo_ready"],
      colors: ["--s1", "--s2", "--s3"], names: ["Needs evidence", "Changes requested", "Demo ready"], labelW: 70, rowH: 34, valueLabels: true,
      tipFmt: (d, k) => `<b>${d.judge}</b> · ${d.remit}<br>${nice[k]}: ${d[k]}`,
    });

    // Fig 7: role heat
    const ag = X.division.agents;
    C.heat($("fig-roles"), {
      rows: ag, cols: X.division.roles, label: (r) => `${r.agent} · ${r.archetype}`, value: (r, j) => r.share[j], max: 0.8, labelW: 150, cellH: 19,
      groupOf: (r) => r.archetype,
      tipFmt: (r, j) => `<b>${r.agent}</b> (${r.archetype})<br>${X.division.roles[j]}: ${r.counts[j]} (${pct(r.share[j])} of actions)<br>specialisation ${r.specialisation.toFixed(2)}`,
    });

    // Concentration by activity
    const L = X.division.lorenz, G = X.division.gini;
    C.line($("fig-lorenz"), {
      series: [
        { name: "Messages", color: "--s1", values: L["Messages"] },
        { name: "Revisions", color: "--s3", values: L["Revisions (all)"] },
        { name: "Peer tests", color: "--s2", values: L["Peer test runs"] },
        { name: "Equality", color: "--axis", values: [[0, 0], [1, 1]] },
      ],
      xMax: 1, yMax: 1, xFormat: d3.format(".0%"), yFormat: d3.format(".0%"), xLabel: "share of residents (least active first) →", height: 260, directLabels: false,
    });

    // Fig 9: room sizes + talk/build
    const tot = d3.sum(X.room_sizes, (r) => r.messages);
    const smallRooms = X.room_sizes.filter((row) => row.size <= 2);
    const largeRooms = X.room_sizes.filter((row) => row.size >= 3);
    const rs = [smallRooms, largeRooms].map((rows, i) => {
      const msgs = d3.sum(rows, (row) => row.messages);
      return { size: i === 0 ? "1–2 speakers" : "3–5 speakers", p: msgs / tot, n: i === 0 ? 1 : 0,
        rooms: d3.sum(rows, (row) => row.rooms), msgs };
    });
    C.bars($("fig-roomsize"), {
      data: rs, x: "size", keys: ["p", "n"], colors: ["--s1", "--s2"], names: ["Projects", "Networking"], yFormat: d3.format(".0%"), yMax: 1, yLabel: "share of messages", height: 260,
      tipFmt: (d, k) => k === "p" ? `<b>Projects · ${d.size}</b><br>${d.rooms} rooms · ${fmt(d.msgs)} messages (${pct(d.p)})` : `<b>Networking · ${d.size}</b><br>${d.n ? "all 207 rooms" : "no rooms"}`,
    });
    const pmax = d3.max(X.talk_build, (p) => p.peer_runs) || 1;
    C.scatter($("fig-talkbuild"), {
      points: X.talk_build, x: "messages", y: "revisions", label: "agent", xLabel: "agent-written messages", yLabel: "revisions authored", height: 260,
      sizeOf: (d) => 4 + 10 * Math.sqrt(d.peer_runs / pmax),
      labelIf: (d) => d.messages > 75 || d.revisions >= 14 || d.peer_runs >= 10,
      tipFmt: (d) => `<b>${d.agent}</b> · ${d.archetype}<br>${d.messages} messages · ${d.revisions} revisions<br>${d.peer_runs} peer test runs · ${fmt(d.reads)} project reads`,
    });

    // Fig 10: explore / premature
    C.bars($("fig-explore"), {
      data: X.explore.map((e) => ({ ...e, label: e.h.toFixed(1) })), x: "label", keys: ["revisions_new", "revisions_old"], stacked: true,
      colors: ["--s4", "--s1"], names: ["to new projects", "to older projects"], xLabel: "active hour →", yLabel: "revisions", height: 240,
      tipFmt: (d) => `<b>${d.h.toFixed(1)}–${(d.h + 0.5).toFixed(1)} h</b><br>${d.new_projects} projects created<br>${d.revisions_new} revisions to projects &lt; 30 min old<br>${d.revisions_old} to older projects`,
    });
    C.bars($("fig-premature"), {
      data: X.premature_reads.map((p) => ({ ...p, label: p.h + "–" + (p.h + 1) })), x: "label", keys: ["share"], colors: ["--s2"], names: ["refused"],
      yFormat: d3.format(".0%"), yMax: 0.1, xLabel: "active hour →", yLabel: "share of reads", height: 240,
      tipFmt: (d) => `<b>hour ${d.label}</b><br>${d.unpublished} of ${fmt(d.n)} reads refused (${pct1(d.share)})`,
    });

    // Fig 11: topics
    C.multiples($("fig-topics"), { series: X.topics.series, xMax: Math.floor(AU.active_h), minW: 210, height: 104 });

    // Fig 12: outcomes
    const on = { working_component: "Working component", incomplete: "Incomplete", written_artifact: "Written artifact", failing_tests: "Failing tests", negative_result: "Negative result" };
    C.hbars($("fig-outcomes"), {
      data: (D.families || []).map((f) => ({ label: on[f.outcome] || f.outcome, n: f.families })), label: "label", keys: ["n"],
      colors: ["--s1"], names: ["families"], valueLabels: true, labelW: 140, rowH: 28,
    });

    // Fig 13: cross-setting
    C.scatter($("fig-cross"), {
      points: X.cross_setting, x: "networking", y: "projects", label: "agent", xLabel: "messages while networking", yLabel: "messages in project run", height: 300,
      labelIf: () => true,
      tipFmt: (d) => `<b>${d.agent}</b><br>networking: ${d.networking} messages<br>projects: ${d.projects} messages`,
    });
  });
})();
