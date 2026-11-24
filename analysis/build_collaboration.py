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

CONVERSATIONS = {
    "civic-consolidation": ("Civic reporting", "civic", [
        ("Suggest one project", "Ganesh suggested combining two similar ideas for reporting local problems."),
        ("Choose the core work", "Aditya agreed to build the reporting workflow and asked Mahboob to choose one part."),
        ("Divide the responsibilities", "Mahboob chose contribution records. Ganesh accepted intake, and Gaurav took an independent walkthrough."),
        ("Agree on file boundaries", "The team separated intake from the workflow. Mahboob read Aditya’s version before adding contribution records."),
        ("Check the shared work", "Independent tests checked the core and the contribution records. Reviewers kept the unfinished storage checks open."),
    ]),
    "joint-record-store": ("Sample record importer", "ingest", [
        ("Offer a trade", "Shriyanshi offered to build an importer in exchange for privacy review."),
        ("Split implementation and review", "Alipat proposed who would build the importer and who would write the acceptance checks."),
        ("Agree on a rule for duplicates", "Shriyanshi accepted the work. Alipat added that reimporting a record must preserve its withdrawn status."),
        ("Save source and leave the test files", "Shriyanshi published the importer and left Alipat to write the independent tests and command-line demo."),
        ("Consolidate and rerun", "The team gathered the work into one reference version. A rerun passed 50 tests. The instructions-only check was still pending."),
    ]),
    "unicode-contract-reuse": ("Bilingual text adapter", "sign", [
        ("Narrow the idea", "Tuhin offered to preserve Hindi and English text in the memory tool while sign-language examples were unavailable."),
        ("Accept a shared component", "Anuj agreed to use the delivered adapter in the memory project."),
        ("Set the scope", "Tuhin committed to retaining the source text and marking unsupported input."),
        ("Ask permission to copy a version", "Tuhin approved one saved version and asked Anuj to check the receiving copy."),
        ("Run the receiving copy", "Anuj recorded 16 passing tests in the memory project. Tuhin inspected that result."),
    ]),
    "memory-approval-reallocation": ("Memory approval", "export", [
        ("Match two ideas", "Anuj offered the memory component. Hiro proposed a step where a person could approve what would be shared."),
        ("Agree on a test case", "They chose a sample maintenance note and agreed what the person would see before approving it."),
        ("Prepare an independent check", "Anuj saved acceptance tests and Gaurav reviewed them. The two components had yet to run together."),
        ("Ask to reallocate the work", "Anuj offered to work in Hiro’s existing project and asked which files Hiro planned to edit."),
        ("Agree on the remaining files", "Hiro and Anuj accepted a file split. The combined version was still pending at the end of the run."),
    ]),
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

WORK_SPLITS = {
    "memory": "Anuj offered to build local memory. Hiro proposed an approval step, and Aditya offered to review how records would be replayed.",
    "d01": "Rajat kept the simulated controller. Dhruv offered independent tests, and Sachit took the consent gate.",
    "value": "Moses and Mahboob joined their record and contribution ideas. They split the disclosure, implementation and review work.",
    "bio": "Kishore kept the study design. Amruth supplied fictional evidence cases, and Pratik took a small part of the study design.",
    "store": "Megabyte asked Gaurav to try the checkout and Vishnu to check what would count as payment evidence.",
    "sol": "Bristin built storage for the transfer record. Hiro reviewed restart behavior and Megabyte contributed compatibility checks.",
    "life": "Shrishti built the learning scoreboard. Hiro reviewed permission design, and independent reviewers raised test and scope issues.",
    "consent": "Dhruv offered to test the consent rules independently. Sachit took the implementation and Moses reviewed how the steps fit together.",
    "reactor": "Bhuvan and Rajat proposed testing each other’s simulated controllers. Abhinav took a separate monitoring question.",
    "audit": "Disha asked for help checking a model-warning idea. Srinitish took evaluation checks and Hiro reviewed how a warning would be used.",
    "evidence": "Amruth took the evidence engine and example cases. Kishore and Pratik offered independent ways to check its output.",
    "field": "Bhuvan asked how to connect monitoring to the controller. Abhinav proposed a separate tool to decide what sensor data could support.",
    "adversarial": "Pratik offered an independent checker in exchange for Amruth’s critique. They agreed on what the engine should report.",
    "force": "Shriyanshi built the search tool. Gaurav asked for a project he could actually run, and Anuj took a separate retrieval check.",
    "qa": "Gaurav described what an independent tester should be able to verify. Srinitish agreed to build an environment that records the result.",
    "block": "Shardul gathered accounts of blocked work. Amruth helped define evidence, and Srinitish agreed to build a checker for the reports.",
    "lending": "Vishnu kept the lending model. Bristin offered independent checks, and Moses’s disclosure work provided a separate use case.",
    "cost": "Pratik owned the audit-budget model. Mahboob narrowed its scope, and Moses offered independent accounting checks.",
    "unblock": "Mahboob proposed recording contributions to the civic tool. Aditya supplied the reporting history, and Sachit took independent checks.",
    "assimilator": "Shriyanshi built the record store. Alipat took the import workflow and acceptance tests, and three reviewers took separate checks.",
    "readiness": "Ganesh requested a handoff checklist. Shardul took the checker and Aditya started connecting it to the civic tool.",
    "recovery": "The team separated exploratory recovery research from building the consent gate. Dhruv took the evaluation.",
    "fieldmap": "Shardul collected coordination cases. Amruth reviewed the inferences and Srinitish checked how the cases were recorded.",
    "heatwriting": "Alipat and Shardul agreed to write about how groups could handle conflicting heat information. Alipat drafted and Shardul reviewed.",
    "qareport": "Gaurav took independent walkthroughs and failure reports. Shardul helped distinguish the different kinds of evidence.",
}


def read(name):
    return json.loads((EVALUATIONS / f"final-{name}.json").read_text())


def short_name(name):
    labels = {"Yakara Ganesh": "Ganesh", "MosesSamPaul johnraj": "Moses"}
    return labels.get(name, name.split()[0].capitalize())


def case_traces(active_hours, cases, families, catalog, evidence):
    def marker(turn, title, detail):
        return {"h": round(active_hours(turn["at"]), 4), "person": short_name(turn["who"]),
                "title": title, "detail": detail}

    paths = {path["key"]: path for path in read("collaboration-paths")["paths"]}
    featured = {
        project: {"title": title, "project": project, "featured": True,
         "steps": [marker(min(stage["exchanges"], key=lambda turn: turn["at"]),
                          step_title, detail) | {"kind": "Conversation"}
                   for stage, (step_title, detail) in zip(paths[key]["stages"], steps, strict=True)]}
        for key, (title, project, steps) in CONVERSATIONS.items()
    }
    labour = {row["key"]: row for row in read("labour")["projects"]}
    kinds = {"message": "Conversation", "run": "Code run", "review": "Review",
             "revision": "Source save", "workspace": "Saved work"}

    def linked_records(refs):
        return [(when, record["person"], ref["type"]) for ref in refs
                for when, record in evidence.get((ref["type"], ref["id"]), [])]

    def recorded_step(when, who, kind, title, detail):
        return marker({"at": when, "who": who}, title, detail) | {"kind": kind}

    conversation_paths = []
    for row in catalog:
        project = row["key"]
        if project in featured:
            conversation_paths.append(featured[project])
            continue
        allocation_refs = [ref for item in labour[project]["allocation"] for ref in item["refs"]]
        when, who, _ = min(record for record in linked_records(allocation_refs) if record[2] == "message")
        steps = [recorded_step(when, who, "Conversation", "Discuss how to divide the work", WORK_SPLITS[project])]
        seen = {when}
        for item in labour[project]["handoffs"]:
            messages = [record for record in linked_records(item["refs"]) if record[2] == "message"]
            if messages:
                when, who, _ = min(messages)
                if when not in seen:
                    steps.append(recorded_step(when, who, "Conversation", "Discuss what can be handed over", item["text"]))
                    seen.add(when)
        milestones = sorted(families[project]["evolution"], key=lambda step: step["at"])
        for i in sorted({0, len(milestones) // 2, len(milestones) - 1}):
            event = milestones[i]
            near = min(linked_records(event["refs"]), key=lambda record: abs(record[0] - event["at"]), default=None)
            if near is None or abs(near[0] - event["at"]) > 1:
                near = (event["at"], "Project record", None)
            when, who, kind = near
            if when not in seen:
                steps.append(recorded_step(when, who, kinds.get(kind, "Milestone"), event["label"], event["text"]))
                seen.add(when)
        conversation_paths.append({"title": row["title"], "project": project, "featured": False,
                                   "steps": sorted(steps, key=lambda step: step["h"])})
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
    return {"conversations": conversation_paths, "conflicts": conflict_paths}


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
    family_for_entry = {project_id: key for key, family in families.items() for project_id in family["project_ids"]}
    activity = {
        key: [{"h": i / 2, "first": 0, "later": 0, "handoffs": 0, "shares": 0}
              for i in range(math.ceil(hours * 2))]
        for key in ("all", *families)
    }

    def record_activity(project_id, timestamp, kind):
        hour = active_hours(timestamp)
        index = min(max(0, int(hour * 2)), len(activity["all"]) - 1)
        activity["all"][index][kind] += 1
        activity[family_for_entry[project_id]][index][kind] += 1

    judge_names = {judge["name"] for judge in snapshot["run_configuration"]["environment"]["judges"]}
    reviews_by_project = defaultdict(list)
    for review in snapshot["reviews"]:
        reviews_by_project[review["project_id"]].append(review["judge"])
    source_events = defaultdict(list)
    handoffs_with_results = 0
    shared_results = 0
    for tool in snapshot["tools"]:
        if tool["name"] in {"project_handoff", "project_share"} and tool["status"] == "completed":
            result = json.loads(tool["result"])
            if result.get("ok"):
                event = result["data"]
                source_events[event["project_id"]].append((tool["name"], tool["owner_id"], event["revision"]))
                kind = "handoffs" if tool["name"] == "project_handoff" else "shares"
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
        "traces": case_traces(active_hours, conflicts, families, catalog, records),
    }


if __name__ == "__main__":
    out = SITE / "static/data/collaboration.json"
    out.write_text(json.dumps(build(), ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Wrote {out.relative_to(SITE)}")
