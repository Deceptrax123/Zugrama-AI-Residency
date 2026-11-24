(async function () {
  const picker = document.getElementById("project-choice");
  const detail = document.getElementById("project-detail");
  const loading = document.getElementById("project-loading");
  const escape = (value) => String(value).replace(/[&<>"]/g, (char) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[char]
  ));

  let data;
  try {
    const response = await fetch("static/data/collaboration.json?v=4");
    if (!response.ok) throw new Error("Project data unavailable");
    data = await response.json();
  } catch {
    loading.textContent = "The project record could not load. Reload the page to try again.";
    return;
  }

  function workshopEntry(entry) {
    const history = entry.versions.length
      ? `<details class="entry-history"><summary>Version history</summary>
        <ol>${entry.versions.map((version) => `<li><b>Version ${version.number} · ${escape(version.author)}</b><br>
          Files: ${version.added} added, ${version.changed} changed, ${version.removed} removed. Runs: ${version.runs}. Handoffs: ${version.handoffs}.</li>`).join("")}</ol>
      </details>`
      : "<p>No source version was saved in this entry.</p>";
    return `<details class="project-entry">
      <summary>${escape(entry.title)} <span>${entry.versions.length} saved</span></summary>
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
      <h3>${escape(project.title)}</h3>
      <p class="project-purpose">${escape(project.purpose)}</p>
      <p class="project-meta">${escape(project.outcome)} · ${entryCount} workshop ${entryCount === 1 ? "entry" : "entries"} · ${saved} saved versions</p>
      <h4>Documented contributions</h4>
      <dl class="role-list">
        ${project.people.map((person) => `<div><dt>${escape(person.name)}${person.judge ? " (judge)" : ""}</dt><dd>${escape(person.role)}</dd></div>`).join("")}
      </dl>
      ${entryCount ? `<h4>Workshop entries</h4>${project.entries.map(workshopEntry).join("")}` : ""}
    `;
  }

  picker.replaceChildren(...data.catalog.map((project) => new Option(project.title, project.key)));
  picker.disabled = false;
  picker.addEventListener("change", () => selectProject(picker.value));
  document.querySelectorAll("[data-project-link]").forEach((link) => {
    link.addEventListener("click", () => selectProject(link.dataset.projectLink));
  });
  selectProject(data.catalog[0].key);
  loading.hidden = true;

  // The explorer also works if the chart library is unavailable.
  if (!window.Charts) return;
  const C = window.Charts;
  const counts = data.project_counts;
  const themes = [
    { name: "Scope of the work", count: data.conflict_topics.scope_requirement },
    { name: "What counted as evidence", count: data.conflict_topics.evidence_standard },
    { name: "Usefulness of a feature", count: data.conflict_topics.usefulness_judgment },
    { name: "Technical behavior", count: data.conflict_topics.technical_claim },
  ];

  C.register(() => {
    const publication = document.getElementById("fig-publication");
    C.hbars(publication, {
      data: [{ name: "First saves", count: counts.with_source }, { name: "Later edits", count: counts.updates }],
      label: "name", keys: ["count"], colors: (row) => row.name === "First saves" ? "--s1" : "--s3",
      labelW: 90, rowH: 35, valueLabels: true, valueW: 30, xMax: 150,
    });
    publication.querySelector("svg").setAttribute("aria-label", `${counts.with_source} first saves and ${counts.updates} later edits.`);
    const conflicts = document.getElementById("fig-conflicts");
    C.hbars(conflicts, {
      data: themes, label: "name", keys: ["count"], colors: ["--s1"],
      labelW: 160, rowH: 30, valueLabels: true, valueW: 26, xMax: 4,
    });
    conflicts.querySelector("svg").setAttribute("aria-label", themes.map((theme) => `${theme.name}, ${theme.count}`).join(". "));
  });
})();
