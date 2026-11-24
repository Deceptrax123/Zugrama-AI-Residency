/* Figures for Study 2 (project teams). Data: static/data/projects.json */
(async function () {
  const D = await (await fetch("static/data/projects.json")).json();
  const C = window.Charts, fmt = C.fmt;
  const $ = (id) => document.getElementById(id);
  const pct = d3.format(".1%");
  const O = D.overview;

  $("run-stats").innerHTML = [
    [fmt(O.messages), "messages"],
    [fmt(O.revisions), "source revisions"],
    [fmt(O.executions), "sandboxed executions"],
    [fmt(O.reviews), "judge reviews"],
    [fmt(O.tool_calls), "tool calls"],
    ["$" + Math.round(O.usd), "API-equivalent spend"],
  ].map(([v, l]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");

  const V = D.verification;
  const rate = (o) => o.fail / o.n;

  C.register(() => {
    // Fig 1: network
    const rmax = d3.max(D.network.nodes, (n) => n.messages);
    C.network($("fig-network"), {
      nodes: D.network.nodes, edges: D.network.edges, height: Math.min(520, Math.max(380, $("fig-network").clientWidth * 0.55)),
      colorOf: (d) => (d.judge ? "--s2" : "--s1"), radius: (d) => 4 + 10 * Math.sqrt(d.messages / rmax),
      tipFmt: (d) => `<b>${d.id}</b>${d.judge ? " (judge)" : ""}<br>${fmt(d.messages)} messages<br>betweenness ${d.betweenness.toFixed(3)}`,
    });

    // Fig 2: failure rates by run kind
    const vrows = [
      { k: "Builder's own runs", o: V.self },
      { k: "Peer: replication", o: V["peer-replication"] },
      { k: "Peer: new probe", o: V["peer-new-probe"] },
      { k: "Peer, after builder passed", o: V.peer_after_self_pass },
    ].map((r) => ({ label: r.k, rate: rate(r.o), ...r.o }));
    C.hbars($("fig-verify"), {
      data: vrows, label: "label", keys: ["rate"], colors: (d) => (d.label.includes("new probe") ? "--s2" : "--s1"),
      stacked: false, valueFmt: d3.format(".0%"), valueLabels: (d) => pct(d.rate), labelW: 170, rowH: 34, xMax: 0.25,
      xLabel: "share of executions that failed →",
      tipFmt: (d) => `<b>${d.label}</b><br>${fmt(d.fail)} failed of ${fmt(d.n)} (${pct(d.rate)})<br>${d.fail_missing} of the failures were missing files/modules`,
    });

    // Fig 3: by role
    const role = [
      { label: "Judges (3)", rep: V.peer_by_judges.n - V.peer_by_judges.new_probes, probe: V.peer_by_judges.new_probes, ...V.peer_by_judges },
      { label: "Residents (25)", rep: V.peer_by_residents.n - V.peer_by_residents.new_probes, probe: V.peer_by_residents.new_probes, ...V.peer_by_residents },
    ];
    C.hbars($("fig-verify-role"), {
      data: role, label: "label", keys: ["rep", "probe"], colors: ["--s1", "--s2"], names: ["Replications", "New probes"],
      labelW: 110, rowH: 40, valueW: 170, valueLabels: (d) => `${fmt(d.n)} runs · ${pct(d.fail / d.n)} failed`, xLabel: "peer executions →",
      tipFmt: (d, k) => `<b>${d.label}</b><br>${k === "rep" ? "Replications" : "New probes"}: ${fmt(d[k])}<br>failure rate overall: ${pct(d.fail / d.n)}`,
    });
    // add a legend line under the chart title once
    if (!$("fig-verify-role").previousElementSibling.classList.contains("legend")) {
      const lg = document.createElement("div"); lg.className = "legend";
      lg.innerHTML = '<span><i style="background:var(--s1)"></i>Replications</span><span><i style="background:var(--s2)"></i>New probes</span>';
      $("fig-verify-role").before(lg);
    }

    // Fig 4: judges
    C.hbars($("fig-judges"), {
      data: D.judges.by_judge, label: "judge", keys: ["needs_evidence", "changes_requested", "simulation_demo_ready"],
      colors: ["--s1", "--s2", "--s3"], names: ["Needs evidence", "Changes requested", "Demo ready"], labelW: 70, rowH: 36, valueLabels: true,
      tipFmt: (d, k) => `<b>${d.judge}</b> · ${d.remit}<br>${{ needs_evidence: "Needs evidence", changes_requested: "Changes requested", simulation_demo_ready: "Demo ready" }[k]}: ${d[k]}`,
    });
    const follow = D.judges.followed_by_revision.filter((r) => r.reviews >= 5).map((r) => ({
      label: { needs_evidence: "Needs evidence", changes_requested: "Changes requested" }[r.decision], share: r.revised / r.reviews, ...r,
    }));
    C.hbars($("fig-follow"), {
      data: follow, label: "label", keys: ["share"], colors: (d) => (d.decision === "changes_requested" ? "--s2" : "--s1"),
      stacked: false, xMax: 1, valueFmt: d3.format(".0%"), valueLabels: (d) => d3.format(".0%")(d.share), labelW: 130, rowH: 40,
      tipFmt: (d) => `<b>${d.label}</b><br>${d.revised} of ${d.reviews} followed by a revision<br>median lag ${d.median_lag_min} min`,
    });

    // Fig 5: room sizes, share of messages
    const totalP = d3.sum(D.room_sizes, (r) => r.messages);
    const rs = [2, 3, 4, 5].map((s) => {
      const r = D.room_sizes.find((x) => x.size === s) || { messages: 0, rooms: 0 };
      return { size: s + " members", p: r.messages / totalP, n: s === 2 ? 1 : 0, rooms: r.rooms, msgs: r.messages };
    });
    C.bars($("fig-roomsize"), {
      data: rs, x: "size", keys: ["p", "n"], colors: ["--s1", "--s2"], names: ["Projects", "Networking"],
      yFormat: d3.format(".0%"), yMax: 1, yLabel: "share of messages", height: 240,
      tipFmt: (d, k) => k === "p" ? `<b>Projects · ${d.size}</b><br>${d.rooms} rooms · ${fmt(d.msgs)} messages (${d3.format(".0%")(d.p)})`
        : `<b>Networking · ${d.size}</b><br>${d.n ? "all 207 rooms · 100% of messages" : "no rooms"}`,
    });

    // Fig 6: tool allocation per agent
    const cats = ["Read state", "Write / publish", "Execute", "Web", "Judge review"];
    const rows = D.tools.by_agent.map((r) => ({ ...r, label: r.judge ? r.agent + " (judge)" : r.agent }));
    C.hbars($("fig-tools"), {
      data: rows, label: "label", keys: cats, colors: ["--s1", "--s2", "--s3", "--s4", "--s5"], names: cats,
      labelW: 110, rowH: 18, xLabel: "tool calls →",
      tipFmt: (d, k) => { const t = d3.sum(cats, (c) => d[c]); return `<b>${d.label}</b><br>${k}: ${fmt(d[k])} (${d3.format(".1%")(d[k] / t)})<br>total ${fmt(t)}`; },
    });

    // Fig 7: read/execute ratio per half hour
    const tl = D.tools.timeline.filter((t) => t.Execute >= 10).map((t) => ({ ...t, label: t.h.toFixed(1), ratio: t["Read state"] / t.Execute }));
    C.bars($("fig-ratio"), {
      data: tl, x: "label", keys: ["ratio"], colors: ["--s1"], yLabel: "reads per execution", xLabel: "wall-clock hour →", height: 240,
      shade: { when: (d) => d.h >= 10, label: "after 7 h pause" },
      tipFmt: (d) => `<b>${d.h.toFixed(1)}–${(d.h + 0.5).toFixed(1)} h</b><br>${fmt(d["Read state"])} reads · ${fmt(d.Execute)} executions<br>ratio ${d.ratio.toFixed(1)} : 1`,
    });

    // Fig 8: talk vs build
    const emax = d3.max(D.talk_build.points, (p) => p.executions);
    C.scatter($("fig-talkbuild"), {
      points: D.talk_build.points, x: "messages", y: "revisions", label: "agent", xLabel: "messages sent", yLabel: "revisions authored",
      sizeOf: (d) => 4 + 9 * Math.sqrt(d.executions / emax),
      labelIf: (d) => d.messages > 125 || d.revisions >= 15 || d.messages < 45,
      tipFmt: (d) => `<b>${d.agent}</b><br>${d.messages} messages · ${d.revisions} revisions<br>${d.executions} executions · $${d.usd.toFixed(2)}`,
    });

    // Fig 9: lifecycle
    C.bars($("fig-revs"), {
      data: D.revisions_per_project.map((r) => ({ ...r, label: String(r.revisions) })), x: "label", keys: ["projects"], colors: ["--s1"],
      xLabel: "revisions", yLabel: "entries", height: 210, tipFmt: (d) => `<b>${d.projects}</b> entries with ${d.revisions} revision${d.revisions === 1 ? "" : "s"}`,
    });
    C.histogram($("fig-ttg"), { values: D.time_to_first_pass_min.values.filter((v) => v > 0), log: true, domain: [-0.5, 3], thresholds: 14, xLabel: "minutes", yLabel: "entries", color: "--s3", height: 210, unit: " min" });

    // Fig 10: outcomes
    const nice = { working_component: "Working component", incomplete: "Incomplete", written_artifact: "Written artifact", failing_tests: "Failing tests", negative_result: "Negative result" };
    C.hbars($("fig-outcomes"), {
      data: (D.families || []).map((f) => ({ label: nice[f.outcome] || f.outcome, n: f.families })), label: "label", keys: ["n"],
      colors: ["--s1"], names: ["families"], valueLabels: true, labelW: 140, rowH: 28,
    });

    // Fig 11: cross-setting
    C.scatter($("fig-cross"), {
      points: D.cross_setting.points.filter((p) => !p.judge), x: "networking", y: "projects", label: "agent",
      xLabel: "messages while networking", yLabel: "messages in project run", height: 300,
      labelIf: (d) => d.projects >= 100 || d.networking >= 175 || d.projects < 45,
      tipFmt: (d) => `<b>${d.agent}</b><br>networking: ${d.networking} messages<br>projects: ${d.projects} messages`,
    });
  });

  C.table($("tbl-agents"), {
    rows: D.agents,
    columns: [
      { key: "agent", label: "Agent" }, { key: "messages", label: "Messages" }, { key: "revisions", label: "Revisions" },
      { key: "executions", label: "Executions" }, { key: "tool_calls", label: "Tool calls" }, { key: "role", label: "Role" },
      { key: "usd", label: "Spend ($)", fmt: (v) => v.toFixed(2) },
    ],
  });
})();
