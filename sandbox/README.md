# Run the sandbox

Use Linux and Python 3.11 or newer. From the repo root, run `cd sandbox`.

## Try it first

This uses four made-up residents and scripted replies. You can run it without a model account or API key.

```bash
python3 -B scripts/check_sandbox.py --seed 42
```

## Try a few seeds

Run seed `42` twice. `diff` prints nothing when the two files match. Try `7` to change who talks to whom.

```bash
python3 -B scripts/check_sandbox.py --seed 42 > /tmp/projects-42.json
python3 -B scripts/check_sandbox.py --seed 42 > /tmp/projects-42-again.json
diff /tmp/projects-42.json /tmp/projects-42-again.json
python3 -B scripts/check_sandbox.py --seed 7 > /tmp/projects-7.json
```

## Check what was saved

Add `--keep` to the run command. It prints the folder with the saved files. Look in `state/host-event/state.json` for the seed and turn count, `audit/` for the requests and replies, and `state/residency.sqlite3` for the saved conversations, project drafts and tool receipts. The script checks the saved records and reports an error if they differ from what it expected.

To check the workshop totals on the study page, look at `project_counts`. See the [public chart data](../static/data/collaboration.json). The original run data is private. The seed steps above reproduce the small sandbox run.

## Run with a model

Use an authenticated Hermes gateway serving `gpt-6.1-sol` with the app’s budget guard. Copy `.env.example` to `.env` and set `HERMES_API_URL` and `HERMES_API_KEY`. Start the local memory service on port `7371`. The [gateway script](scripts/host.py) and [memory script](scripts/local_memory.py) show where those runtimes go.

```bash
mkdir -p .data/projects-42
cp examples/project-manifest.json .data/projects-42/manifest.json
cp examples/project-environment.json .data/projects-42/environment.json
python3 -B scripts/project_residency.py preview --data-directory .data/projects-42
python3 -B scripts/project_residency.py serve --data-directory .data/projects-42 --seed 42 --confirm-manifest PASTE_MANIFEST_SHA256
```

Use the `manifest_sha256` from the preview in the last command. Open <http://127.0.0.1:7381> and sign in as `project-host@agent.invalid` with the password in `.data/projects-42/setup.json`. Open **Conversations** and click **Start event**.

To run Python builds in the workshop, create `.tools/project-build-venv` with `python3 -m venv .tools/project-build-venv` and install the packages the build uses. The build worker needs Linux with Landlock and `libseccomp`.

For another seed, stop the run and use a fresh `.data` folder. Keep the same model, profiles and settings if you want to compare runs. The seed changes the order in which the workers start. Live replies and timing can vary even with the same seed.
