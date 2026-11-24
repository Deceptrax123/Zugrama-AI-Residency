(async function () {
  const picker = document.getElementById("project-choice");
  const detail = document.getElementById("project-detail");
  const loading = document.getElementById("project-loading");
  const escape = (value) => String(value).replace(/[&<>"]/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[char]
  ));

  let data;
  try {
    const response = await fetch("static/data/collaboration.json?v=7");
    if (!response.ok) throw new Error("Project data unavailable");
    data = await response.json();
  } catch {
    loading.textContent = "The project record could not load. Reload the page to try again.";
    return;
  }

  const when = (h) => window.Charts ? window.Charts.clock(h) : `${h.toFixed(2)} h`;

  function evidenceCard(checkpoint) {
    const receipts = checkpoint.receipts.map((receipt) => {
      const subject = [receipt.entry, receipt.version == null ? "" : `version ${receipt.version}`].filter(Boolean).join(" · ");
      const facts = [receipt.outcome, receipt.person, `${when(receipt.h)} active time`].filter(Boolean).join(" · ");
      return `<li><b>${escape(receipt.kind)}</b>${subject ? ` <span>${escape(subject)}</span>` : ""}
        <span class="receipt-meta">${escape(facts)}${receipt.fingerprint ? ` · source <code>${escape(receipt.fingerprint)}</code>` : ""}</span></li>`;
    }).join("");
    return `<article class="project-checkpoint">
      <h5>${escape(checkpoint.title)}</h5>
      <p>${escape(checkpoint.detail)}</p>
      <ul class="project-receipts">${receipts}</ul>
    </article>`;
  }

  function projectReview(review) {
    return `<div class="project-review">
      <div class="project-finding"><h4>What the record shows</h4><p>${escape(review.observed)}</p></div>
      <div class="project-review-grid">
        <div><h4>What they proposed</h4><p>${escape(review.goal)}</p></div>
        <div><h4>How they divided the work</h4><p>${escape(review.collaboration)}</p></div>
        <div><h4>What changed along the way</h4><p>${escape(review.decision)}</p></div>
        <div><h4>Where it stood at cutoff</h4><p>${escape(review.open)}</p></div>
      </div>
      <details class="project-evidence">
        <summary>Evidence behind this analysis</summary>
        ${review.checkpoints.map(evidenceCard).join("")}
      </details>
    </div>`;
  }

  function workshopEntry(entry) {
    const history = entry.versions.length
      ? `<details class="entry-history"><summary>Version history</summary>
        <ol>${entry.versions.map((version) => `<li><b>Version ${version.number} · ${escape(version.author)}</b> · ${when(version.h)}<br>
          Files: ${version.added} added, ${version.changed} changed, ${version.removed} removed. Runs: ${version.runs}. Handoffs: ${version.handoffs}.</li>`).join("")}</ol>
      </details>`
      : "<p>No source version was saved in this entry.</p>";
    const latest = entry.latest_check;
    const latestOutcome = latest && (latest.successful + latest.unsuccessful > 0
      ? `<p class="project-latest-check">Latest saved version (${latest.version}) recorded ${latest.successful} successful and ${latest.unsuccessful} unsuccessful exits.</p>`
      : `<p class="project-latest-check">Latest saved version (${latest.version}) had no recorded run.</p>`);
    return `<details class="project-entry">
      <summary>${escape(entry.title)} <span>${entry.versions.length} saved</span></summary>
      ${latestOutcome || ""}
      <div class="table-wrap" tabindex="0" aria-label="Scrollable contributor table">
        <table class="compare">
          <thead><tr>
            <th scope="col">Agent</th><th scope="col">Versions saved</th><th scope="col">Code runs</th>
            <th scope="col">Reviews</th><th scope="col">Handoffs</th><th scope="col">Room shares</th>
          </tr></thead>
          <tbody>
            ${entry.people.map((person) => `<tr><th scope="row">${escape(person.name)}${person.opened ? " (opened entry)" : ""}</th>
              <td>${person.versions}</td><td>${person.runs}</td><td>${person.reviews}</td><td>${person.handoffs}</td><td>${person.shares}</td></tr>`).join("")}
          </tbody>
        </table>
      </div>
      ${history}
    </details>`;
  }

  function selectProject(key) {
    const project = data.catalog.find((item) => item.key === key);
    picker.value = project.key;
    const saved = project.entries.reduce((sum, entry) => sum + entry.versions.length, 0);
    const entryCount = project.entries.length;
    detail.innerHTML = `
      <h3 id="project-${escape(project.key)}">${escape(project.title)}</h3>
      <p class="project-purpose">${escape(project.purpose)}</p>
      <p class="project-meta">${escape(project.outcome)} · ${entryCount} workshop ${entryCount === 1 ? "entry" : "entries"} · ${saved} saved versions</p>
      <p class="project-permalink"><a href="#project-${escape(project.key)}">Link to this project analysis</a></p>
      ${projectReview(project.review)}
      <h4>Documented contributions</h4>
      <dl class="role-list">
        ${project.people.map((person) => `<div><dt>${escape(person.name)}${person.judge ? " (judge)" : ""}</dt><dd>${escape(person.role)}</dd></div>`).join("")}
      </dl>
      ${entryCount ? `<h4>Workshop entries</h4>${project.entries.map(workshopEntry).join("")}` : ""}
    `;
  }

  function followProjectLink() {
    const key = location.hash.startsWith("#project-") ? location.hash.slice(9) : "";
    if (!data.catalog.some((project) => project.key === key)) return false;
    selectProject(key);
    window.requestAnimationFrame(() => document.getElementById(`project-${key}`)?.scrollIntoView?.());
    return true;
  }

  picker.replaceChildren(...data.catalog.map((project) => new Option(project.title, project.key)));
  picker.disabled = false;
  picker.addEventListener("change", () => selectProject(picker.value));
  document.querySelectorAll("[data-project-link]").forEach((link) => {
    link.addEventListener("click", () => selectProject(link.dataset.projectLink));
  });
  window.addEventListener("hashchange", followProjectLink);
  if (!followProjectLink()) selectProject(data.catalog[0].key);
  loading.hidden = true;

  // The explorer also works if the chart library is unavailable.
  if (!window.Charts) return;
  const C = window.Charts;
  const $ = (id) => document.getElementById(id);
  const themes = [
    { name: "Scope of the work", count: data.conflict_topics.scope_requirement },
    { name: "What counted as evidence", count: data.conflict_topics.evidence_standard },
    { name: "Usefulness of a feature", count: data.conflict_topics.usefulness_judgment },
    { name: "Technical behavior", count: data.conflict_topics.technical_claim },
  ];

  function setupTraces(pickerId, chartId, stepsId, paths, onSelect) {
    const select = $(pickerId);
    select.replaceChildren(...paths.map((path, i) => new Option(path.title, i)));
    select.disabled = false;
    function render() {
      const path = paths[Number(select.value)];
      C.trace($(chartId), { steps: path.steps, label: (step) => step.person, format: C.clock, axisLabel: "Active time since start" });
      $(stepsId).innerHTML = path.steps.map((step) => `<li><b>${escape(step.title)}</b>
        <span>${step.kind ? `${escape(step.kind)} · ` : ""}${escape(step.person)} · ${C.clock(step.h)}</span><p>${escape(step.detail)}</p></li>`).join("");
      onSelect(path);
    }
    select.addEventListener("change", render);
    C.register(render);
  }

  setupTraces("conversation-project", "fig-project-conversation", "project-conversation-steps", data.traces.conversations, (path) => {
    $("conversation-project-link").dataset.projectLink = path.project;
    $("conversation-reading").textContent = path.featured
      ? "Selected turns from the project’s recorded exchanges."
      : "Linked conversations and dated milestones from the project record.";
  });
  const replies = {
    accepted: "The proposal was accepted.", partly_accepted: "The proposal was partly accepted.",
    maintained: "The previous position was maintained.", rejected: "The proposal was declined.",
  };
  const followThrough = {
    applied: "The later record shows the agreed action was carried out.",
    partial: "Part of the agreed work was carried out.",
    not_applied: "The agreed change had not been delivered by the last retained follow-up.",
    not_applicable: "The response left no agreed change to implement.",
  };
  setupTraces("conflict-case", "fig-conflict-path", "conflict-steps", data.traces.conflicts, (path) => {
    $("conflict-reading").textContent = `${replies[path.response]} ${followThrough[path.follow_through]}`;
  });

  const activity = $("activity-project");
  activity.replaceChildren(new Option("All projects", "all"), ...data.catalog.filter((project) => project.entries.length)
    .map((project) => new Option(project.title, project.key)));
  activity.disabled = false;
  const formatHour = (h) => C.clock(h).slice(0, -3);
  const charts = [
    { id: "fig-publication", keys: ["first", "later"], colors: ["--s1", "--s3"], names: ["First saves", "Later saves"] },
    { id: "fig-handoffs", keys: ["handoffs", "shares"], colors: ["--s2", "--s4"], names: ["Version handoffs", "Room shares"] },
  ];

  function renderActivity() {
    const rows = data.activity.bins[activity.value];
    for (const { id, keys, colors, names } of charts) {
      const chart = $(id);
      const yMax = Math.max(4, d3.max(rows, (row) => d3.sum(keys, (key) => row[key])));
      C.bars(chart, { data: rows, x: "h", keys, colors, names, stacked: true, xTickFormat: formatHour,
        yMax, yFormat: d3.format("d"), xLabel: "Active time", height: 205,
        tipFmt: (row) => `<b>${formatHour(row.h)}–${formatHour(Math.min(row.h + 0.5, data.activity.hours))}</b><br>${
          keys.map((key, i) => `${names[i]}: ${row[key]}`).join("<br>")}`,
      });
      chart.querySelector("svg").setAttribute("aria-label", `${names.join(" and ")} by half hour. Values are in the table below.`);
    }
    const total = (key) => d3.sum(rows, (row) => row[key]);
    $("activity-reading").textContent = `${total("first")} first saves, ${total("later")} later saves, ${total("handoffs")} version handoffs and ${total("shares")} room shares.`;
    $("tbl-activity").innerHTML = `<thead><tr><th scope="col">Interval start</th><th scope="col">First saves</th><th scope="col">Later saves</th>
      <th scope="col">Handoffs</th><th scope="col">Room shares</th></tr></thead><tbody>${rows.map((row) =>
        `<tr><th scope="row">${formatHour(row.h)}</th><td>${row.first}</td><td>${row.later}</td><td>${row.handoffs}</td><td>${row.shares}</td></tr>`).join("")}</tbody>`;
  }
  activity.addEventListener("change", renderActivity);
  C.register(renderActivity);

  C.register(() => {
    const conflicts = $("fig-conflicts");
    C.hbars(conflicts, {
      data: themes, label: "name", keys: ["count"], colors: ["--s1"],
      labelW: 160, rowH: 30, valueLabels: true, valueW: 26, xMax: 4,
    });
    conflicts.querySelector("svg").setAttribute("aria-label", themes.map((theme) => `${theme.name}, ${theme.count}`).join(". "));
  });
})();
