"""Export dated project activity without exposing the underlying messages or code."""

import sqlite3
from collections import defaultdict

from active_clock import WORKSPACE

DATABASE = WORKSPACE / "residency_app/.data/project-completion-private-run2/state/residency.sqlite3"


def read_automated_message_ids():
    with sqlite3.connect(f"{DATABASE.as_uri()}?mode=ro", uri=True) as connection:
        return {message_id for table in ("lab_posts", "workspace_revisions", "agent_boards")
                for (message_id,) in connection.execute(f"SELECT message_id FROM {table} WHERE message_id IS NOT NULL")}


def evidence_refs(node):
    if isinstance(node, dict):
        if "type" in node and "id" in node:
            yield node["type"], node["id"]
        for child in node.values():
            yield from evidence_refs(child)
    elif isinstance(node, list):
        for child in node:
            yield from evidence_refs(child)


def build_timelines(snapshot, families, editorial, labour, case_notes, records, messages,
                    transfers, active_hours, time_bin, short_name):
    names = snapshot["names"]
    judges = {short_name(judge["name"]) for judge in snapshot["run_configuration"]["environment"]["judges"]}
    entries = {entry["id"]: entry for entry in snapshot["projects"]}
    reviews_by_entry = defaultdict(list)
    for review in snapshot["reviews"]:
        reviews_by_entry[review["project_id"]].append(review)
    notes_by_family = defaultdict(list)
    for note in case_notes:
        for key in note["project_keys"]:
            notes_by_family[key].append(note)

    def event(kind, key, identifier):
        when, receipt = records[key, identifier][0]
        return {field: receipt[field] for field in ("person", "h", "entry", "version", "outcome")
                if field in receipt} | {"kind": kind, "bin": time_bin(when)}

    timelines = {}
    for key, family in families.items():
        refs = sorted(set(evidence_refs([family, editorial[key], labour[key], notes_by_family[key]])))
        events = []
        drafts = set()
        for kind, identifier in refs:
            if kind == "message" and identifier in messages:
                message = messages[identifier]
                events.append({"kind": "discussion", "person": short_name(names[message["sender_id"]]),
                               "h": round(active_hours(message["created_at"]), 4),
                               "bin": time_bin(message["created_at"])})
            if kind == "workspace":
                for when, receipt in records.get((kind, identifier), []):
                    draft = (identifier.split(":")[0], receipt["version"])
                    if draft not in drafts:
                        drafts.add(draft)
                        events.append({"kind": "draft", "person": receipt["person"], "h": receipt["h"],
                                       "bin": time_bin(when),
                                       "version": receipt["version"]})
        for entry_id in family["project_ids"]:
            entry = entries[entry_id]
            events.extend(event("save", "revision", f'{entry_id}:{version["revision"]}')
                          for version in entry["revisions"])
            events.extend(event("run", "run", run["id"]) for run in entry["runs"])
            events.extend(event("review", "review", review["id"]) for review in reviews_by_entry[entry_id])
            events.extend(transfers[entry_id])

        roles = {short_name(person["name"]): person["role"] for person in editorial[key]["collaborators"]}
        participants = set(roles) | {short_name(name) for name in family["resident_names"]}
        participants.update(event["person"] for event in events)
        timelines[key] = {
            "people": [{"name": name, "role": roles.get(name, ""), "judge": name in judges}
                       for name in sorted(participants, key=str.casefold)],
            "events": sorted(events, key=lambda item: (item["h"], item["person"], item["kind"])),
        }
    return timelines
