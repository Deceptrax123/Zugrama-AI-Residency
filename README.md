# Re-running Is Not Reviewing

Research project page for **Study 2** of the Agent Residency Studies: a log-level
analysis of 25 resident agents and 3 judge agents (GPT-6.1 Sol) building software
together (2,731 messages, 209 revisions, 577 sandboxed executions, 81 reviews,
22,146 tool calls).

Companion page: [Study 1 — Everyone Meets Everyone, Once](https://deceptrax123.github.io/agent-networking-study/).

## Layout

| Path | What it is |
| --- | --- |
| `index.html` | The page (static; D3 7.9.0 from cdnjs) |
| `static/data/projects.json` | All figure data (aggregates only) |
| `static/js/charts.js` | Shared chart kit (tooltips, light/dark) |
| `static/js/main.js` | Figure definitions for this page |
| `analysis/build_data.py` | Rebuilds the figure data from the frozen records |

## Rebuilding the data

`analysis/build_data.py` reads, without modifying, the parent sandbox workspace
(`residency_app/experiments/project-completion/evaluations/final-snapshot.json`,
the run's usage ledger, the earlier audit's family classifications and the
networking archive for the cross-setting comparison). It never executes resident
code. Those private records are **not** part of this repository.

```bash
python -m venv .venv && .venv/bin/pip install -r analysis/requirements.txt
.venv/bin/python analysis/build_data.py                 # first-name labels
.venv/bin/python analysis/build_data.py --labels codes  # pseudonymous P01…, J1…
```

Peer executions are classified as *replications* (a command already run on that
project) or *new probes* (a command not previously run) by exact string match.

## Deploying

GitHub Pages → *Deploy from a branch* → `main` / root. `.nojekyll` is included.

## What is and is not published

Aggregate statistics, per-agent counts, first-name labels and short,
rule-selected excerpts of agent-generated messages and judge reviews. No source
code, application forms, private memory or contact details.

## Run audit and hypothesis tests

`analysis/science.py` audits the run (scheduler gaps, provider errors, ledger
reconciliation, platform-generated posts, prompt changes), runs the hypothesis
tests (exact, resampling and stratified methods with Benjamini–Hochberg
adjustment), fits the topic model, computes division-of-work measures and
selects conversation excerpts by stated rules. It writes
`static/data/science.json`.

```bash
pip install -r analysis/requirements.txt
python analysis/build_data.py
python analysis/science.py
```
