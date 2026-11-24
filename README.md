# Zugrama Residency

A standalone research page following how 25 resident agents chose collaborators,
divided work and built software in a shared workshop. The project explorer covers
29 lines of work and 87 workshop entries. It distinguishes saved source versions,
code runs, judge reviews, room shares and version handoffs.

[Live study](https://deceptrax123.github.io/agent-project-study/)

## Rebuild the project explorer

Run this from the site checkout inside the sandbox workspace:

```bash
python3 analysis/build_collaboration.py
```

The script reads the frozen project snapshot, the active-time request audit,
and the project overview, collaboration and disagreement reviews under
`residency_app/experiments/project-completion/evaluations/`. It exports the
public catalogue and counts to `static/data/collaboration.json`. The export
contains project titles, first-name labels, version metadata, contribution counts,
half-hour activity totals and selected conversation and disagreement timelines.
The build never executes resident code.

## Supplementary analysis

The original descriptive and exploratory analysis builders produce
`static/data/projects.json` and `static/data/science.json` from the frozen
project records. Their dependencies are listed in `analysis/requirements.txt`.
Both support `--labels codes`.

GitHub Pages serves the static site from the root of `main`.
