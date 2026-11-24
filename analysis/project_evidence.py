"""Ground project notes and checkpoint cards in the frozen workshop records."""

import json
from collections import Counter, defaultdict
from pathlib import Path

NOTES = Path(__file__).with_name("project_notes.json")
FIELDS = ("goal", "collaboration", "decision", "observed", "open")
REVIEW_DECISIONS = {
    "needs_evidence": "More evidence requested",
    "changes_requested": "Changes requested",
    "simulation_demo_ready": "Simulation demo ready",
}


def build_evidence(snapshot, active_hours, short_name):
    records = defaultdict(list)
    latest_checks = {}
    names = snapshot["names"]

    def save(kind, identifier, record, actor, label, **details):
        when = record["created_at"]
        facts = {"kind": label, "person": short_name(names[record[actor]]),
                 "h": round(active_hours(when), 4), **details}
        records[kind, identifier].append((when, facts))

    projects = {entry["id"]: entry for entry in snapshot["projects"]}
    for key, entry in projects.items():
        versions = {revision["revision"]: revision for revision in entry["revisions"]}
        latest = max(versions, default=None)
        latest_results = Counter()
        for revision, saved in versions.items():
            save("revision", f"{key}:{revision}", saved, "author", "Source save",
                 entry=entry["title"], version=revision, fingerprint=saved["source_hash"][:12])
        for run in entry["runs"]:
            result = json.loads(run["result"])
            revision = run["revision"]
            source = versions.get(revision)
            matches = source is not None and result.get("source_sha256") == source["source_hash"]
            if not matches:
                raise ValueError(f"Run receipt does not match saved source for {entry['title']} v{revision}")
            status = "successful" if result["ok"] else "unsuccessful"
            if revision == latest:
                latest_results[status] += 1
            kind = "Simulated task" if run["kind"] == "village_verify" else "Code run"
            save("run", run["id"], run, "author", kind, entry=entry["title"], version=revision,
                 fingerprint=source["source_hash"][:12],
                 outcome="Successful exit" if result["ok"] else "Unsuccessful exit")
        if latest is not None:
            latest_checks[key] = {"version": latest, "successful": latest_results["successful"],
                                  "unsuccessful": latest_results["unsuccessful"]}

    for review in snapshot["reviews"]:
        decision = review["decision"]
        save("review", review["id"], review, "judge", "Review", entry=projects[review["project_id"]]["title"],
             version=review["revision"], outcome=REVIEW_DECISIONS.get(decision, decision.replace("_", " ").capitalize()))
    automated = set()
    for workspace in snapshot["workspaces"]:
        for saved in workspace["revisions"]:
            revision = saved["revision"]
            save("workspace", f'{workspace["id"]}:{revision}', saved, "owner_id", "Saved workspace", version=revision)
            save("workspace", workspace["id"], saved, "owner_id", "Saved workspace", version=revision)
            automated.add(saved.get("message_id"))
    for message in snapshot["messages"]:
        if message["id"] not in automated:
            save("message", message["id"], message, "sender_id", "Conversation")
    return records, latest_checks


def project_reviews(families, records):
    notes = json.loads(NOTES.read_text())
    if notes.keys() != families.keys():
        raise ValueError("Project notes must cover each project family once")
    reviews = {}
    for key, note in notes.items():
        checkpoints = []
        for index in note["checkpoints"]:
            milestone = families[key]["evolution"][index]
            refs = dict.fromkeys((ref["type"], ref["id"]) for ref in milestone["refs"])
            receipts = []
            for ref in refs:
                if ref not in records:
                    raise ValueError(f"Unresolved checkpoint reference for {key}: {ref[0]}")
                nearest = min(records[ref], key=lambda record: abs(record[0] - milestone["at"]))
                receipts.append(nearest[1])
            checkpoints.append({"title": milestone["label"], "detail": milestone["text"],
                                "receipts": sorted(receipts, key=lambda receipt: receipt["h"])})
        reviews[key] = {field: note[field] for field in FIELDS} | {"checkpoints": checkpoints}
    return reviews
