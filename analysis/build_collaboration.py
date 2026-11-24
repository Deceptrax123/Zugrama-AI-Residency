"""Build the standalone Residency explorer from the frozen project run.

Exports titles, first-name labels, contribution counts and reviewed evidence.
Source files, tool payloads, application records and raw messages stay local.
"""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from active_clock import make_active_clock, read_request_times
from project_evidence import build_evidence, project_reviews
from project_timeline import build_timelines, read_automated_message_ids

SITE = Path(__file__).resolve().parents[1]
EVALUATIONS = SITE.parents[1] / "residency_app/experiments/project-completion/evaluations"

# Short descriptions for projects with multiple workshop entries or technical titles.
PURPOSES = {
    "civic": "Report a local problem, see who responded, and confirm or reopen the fix.",
    "ingest": "Import sample records and keep track of consent and corrections.",
    "sign": "Explore sign input and preserve Hindi and English text through an adapter.",
    "export": "Preview and approve which saved memories an assistant can share.",
    "memory": "Keep useful notes offline and let a user remove selected memories.",
    "d01": "Test a controller on simulated brain-signal data.",
    "value": "Share selected parts of a private contribution record.",
    "bio": "Read and compare evidence from fictional biosignal studies.",
    "store": "Deliver a digital item after a simulated payment.",
    "sol": "Keep a record of transfers that survives a restart.",
    "life": "Track progress through a set of practical life-skills exercises.",
    "consent": "Check permission before releasing a synthetic record.",
    "reactor": "Simulate how an algae reactor controller handles faults.",
    "audit": "Test whether signals inside a model can warn that it is about to make an error.",
    "evidence": "Show how corrections change which claims a reader can rely on.",
    "field": "Check what a sensor reading can support and where it came from.",
    "adversarial": "Independently check whether an evidence tool follows its stated rules.",
    "force": "Find relevant projects from context a user has agreed to share.",
    "qa": "Check whether a delegated task actually produced the promised result.",
    "block": "Check that a reported obstacle points to a source someone can inspect.",
    "lending": "Track sample loans and decide which records can be shared.",
    "cost": "Explore how to spend a limited budget for checking contributions.",
    "unblock": "Record what someone contributed and whether that work still counts after a case reopens.",
    "assimilator": "Try importing and retrieving sample records by following written instructions.",
    "readiness": "Check whether another person could take over a civic reporting project.",
    "recovery": "Explore whether a simulated brain signal could reproduce a key.",
    "fieldmap": "Map places where research collaborators get stuck waiting on each other.",
    "heatwriting": "Draft an essay about how communities could govern heat-health responses.",
    "qareport": "Document independent walkthroughs, problems found and repairs checked.",
}

STATUS = {
    "working_component": "Component tested",
    "incomplete": "Work unfinished",
    "failing_tests": "Tests still failing",
    "negative_result": "Negative result",
    "written_artifact": "Written work",
}

CONFLICTS = {
    "retain-lifecycle-fix-expectation": "Which status should the civic test expect?",
    "no-civic-memory-consumer": "Did civic reporting need memory lookup?",
    "close-checkpoint-retain-broader-label": "What could a passing component close?",
    "keep-local-fixture-scope": "Did the algae controller need extra storage?",
    "public-file-sufficient": "Was a public file enough for distribution?",
    "tracker-review-not-second-app": "A privacy review or a second tracker?",
    "payment-proof-standard-retained": "What counted as proof of payment?",
    "assistance-does-not-become-independent-discovery": "Could a coached result count as independent?",
    "monitor-review-without-invented-integration": "Was there a place for model monitoring?",
    "recovery-advice-accepted-not-delivered": "Would the restart repair be delivered?",
}

def read(name):
    return json.loads((EVALUATIONS / f"final-{name}.json").read_text())


def short_name(name):
    labels = {"Yakara Ganesh": "Ganesh", "MosesSamPaul johnraj": "Moses"}
    return labels.get(name, name.split()[0].capitalize())


def conflict_traces(active_hours, cases):
    def marker(turn, title, detail):
        return {"h": round(active_hours(turn["at"]), 4), "person": short_name(turn["who"]),
                "title": title, "detail": detail}

    case_by_key = {case["key"]: case for case in cases}
    conflict_paths = []
    for key, title in CONFLICTS.items():
        case = case_by_key[key]
        proposal = min(case["proposal"]["quotes"], key=lambda turn: turn["at"])
        reply = min(case["response"]["quotes"], key=lambda turn: turn["at"])
        later = max(case["later"]["quotes"], key=lambda turn: turn["at"])
        conflict_paths.append({
            "title": title, "response": case["response_type"], "follow_through": case["follow_through"],
            "steps": [marker(proposal, "Issue raised", case["proposal"]["text"]),
                      marker(reply, "First recorded reply", case["response"]["text"]),
                      marker(later, "Later evidence", case["later"]["text"])],
        })
    return conflict_paths


def build():
    snapshot = read("snapshot")
    names = snapshot["names"]
    projects = {project["id"]: project for project in snapshot["projects"]}
    families = {family["key"]: family for family in read("narratives")["families"]}
    editorial = {project["key"]: project for project in read("project-overview")["projects"]}
    active_hours, _ = make_active_clock(snapshot["started_at"], read_request_times())
    records, latest_checks = build_evidence(snapshot, active_hours, short_name)
    reviews = project_reviews(families, records)
    hours = active_hours(snapshot["cutoff_at"])
    bin_count = math.ceil(hours * 2)
    family_for_entry = {project_id: key for key, family in families.items() for project_id in family["project_ids"]}
    activity = {
        key: [{"h": i / 2, "first": 0, "later": 0, "handoffs": 0, "shares": 0}
              for i in range(bin_count)]
        for key in ("all", *families)
    }

    def time_bin(timestamp):
        return min(max(0, int(active_hours(timestamp) * 2)), bin_count - 1)

    def record_activity(project_id, timestamp, kind):
        index = time_bin(timestamp)
        activity["all"][index][kind] += 1
        activity[family_for_entry[project_id]][index][kind] += 1

    judge_names = {judge["name"] for judge in snapshot["run_configuration"]["environment"]["judges"]}
    reviews_by_project = defaultdict(list)
    for review in snapshot["reviews"]:
        reviews_by_project[review["project_id"]].append(review["judge"])
    source_events = defaultdict(list)
    transfers = defaultdict(list)
    handoffs_with_results = 0
    shared_results = 0
    for tool in snapshot["tools"]:
        if tool["name"] in {"project_handoff", "project_share"} and tool["status"] == "completed":
            result = json.loads(tool["result"])
            if result.get("ok"):
                event = result["data"]
                source_events[event["project_id"]].append((tool["name"], tool["owner_id"], event["revision"]))
                kind = "handoffs" if tool["name"] == "project_handoff" else "shares"
                transfers[event["project_id"]].append({
                    "kind": "handoff" if kind == "handoffs" else "share",
                    "person": short_name(names[tool["owner_id"]]),
                    "h": round(active_hours(tool["finished_at"]), 4),
                    "bin": time_bin(tool["finished_at"]),
                    "entry": projects[event["project_id"]]["title"],
                    "version": event["revision"],
                })
                record_activity(event["project_id"], tool["finished_at"], kind)
                if tool["name"] == "project_handoff" and event["shared_receipts"]:
                    handoffs_with_results += 1
                    shared_results += len(event["shared_receipts"])

    def entry(project):
        project_id = project["id"]
        authors = Counter(revision["author"] for revision in project["revisions"])
        runners = Counter(run["author"] for run in project["runs"])
        judges = Counter(reviews_by_project[project_id])
        handoffs = Counter(actor for kind, actor, _ in source_events[project_id] if kind == "project_handoff")
        shares = Counter(actor for kind, actor, _ in source_events[project_id] if kind == "project_share")
        creator = project["author"]
        members = authors.keys() | runners.keys() | judges.keys() | handoffs.keys() | shares.keys() | {creator}
        people = [
            {"name": short_name(names[member]), "opened": member == creator,
             "versions": authors[member], "runs": runners[member], "reviews": judges[member],
             "handoffs": handoffs[member], "shares": shares[member]}
            for member in sorted(members, key=lambda member: (
                member != creator, -authors[member], -runners[member], -judges[member], names[member].casefold()
            ))
        ]
        runs_by_version = Counter(run["revision"] for run in project["runs"])
        handoffs_by_version = Counter(version for kind, _, version in source_events[project_id] if kind == "project_handoff")
        versions = []
        previous = {}
        for rev in sorted(project["revisions"], key=lambda rev: rev["revision"]):
            files = json.loads(rev["files"])
            number = rev["revision"]
            record_activity(project_id, rev["created_at"], "first" if number == 1 else "later")
            versions.append({
                "number": number, "author": short_name(names[rev["author"]]), "files": len(files),
                "added": len(files.keys() - previous.keys()),
                "changed": sum(files[file] != previous[file] for file in files.keys() & previous.keys()),
                "removed": len(previous.keys() - files.keys()),
                "runs": runs_by_version[number], "handoffs": handoffs_by_version[number],
                "h": round(active_hours(rev["created_at"]), 4),
            })
            previous = files
        return {"title": project["title"], "versions": versions, "people": people,
                "latest_check": latest_checks.get(project_id)}

    catalog = []
    for key, purpose in PURPOSES.items():
        family, overview = families[key], editorial[key]
        people = [{"name": short_name(person["name"]), "role": person["role"],
                   "judge": person["name"] in judge_names} for person in overview["collaborators"]]
        catalog.append({"key": key, "title": overview["title"], "purpose": purpose,
                        "outcome": STATUS[family["status"]], "people": people,
                        "review": reviews[key],
                        "entries": [entry(projects[project_id]) for project_id in family["project_ids"]]})

    versioned = [project for project in projects.values() if project["revisions"]]
    revisions = [(project, rv) for project in versioned for rv in project["revisions"]]
    other_authors = [rv["author"] for project, rv in revisions if rv["author"] != project["author"]]
    handoff_counts = Counter(project_id for project_id, events in source_events.items()
                             for kind, _, _ in events if kind == "project_handoff")
    conflicts = read("contestation")["cases"]
    automated_messages = read_automated_message_ids()
    messages = {message["id"]: message for message in snapshot["messages"]
                if message["id"] not in automated_messages}
    labour = {row["key"]: row for row in read("labour")["projects"]}
    paths = read("collaboration-paths")["paths"]
    timelines = build_timelines(
        snapshot, families, editorial, labour, paths + conflicts, records,
        messages, transfers, active_hours, time_bin, short_name,
    )
    return {
        "project_counts": {
            "opened": len(projects),
            "with_source": len(versioned),
            "versions": len(revisions),
            "updates": len(revisions) - len(versioned),
            "multiple_authors": sum(len({rv["author"] for rv in p["revisions"]}) > 1 for p in versioned),
            "versions_by_other_agents": len(other_authors),
            "agents_contributing_to_others": len(set(other_authors)),
            "handoffs": handoff_counts.total(),
            "entries_with_handoffs": len(handoff_counts),
            "handoffs_with_results": handoffs_with_results,
            "attached_results": shared_results,
            "private_to_room": sum(kind == "project_share" for events in source_events.values() for kind, _, _ in events),
            "public_at_cutoff": sum(p["visibility"]["visibility"] == "public" for p in versioned),
            "runs": sum(len(p["runs"]) for p in projects.values()),
        },
        "conflict_topics": dict(Counter(case["claim_type"] for case in conflicts)),
        "catalog": catalog,
        "activity": {"hours": round(hours, 3), "bins": activity},
        "timelines": timelines,
        "traces": {"conflicts": conflict_traces(active_hours, conflicts)},
    }


if __name__ == "__main__":
    out = SITE / "static/data/collaboration.json"
    out.write_text(json.dumps(build(), ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Wrote {out.relative_to(SITE)}")
