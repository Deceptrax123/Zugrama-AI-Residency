"""Active-hour clock shared by the Residency analysis exports."""

import json
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[3]
AUDIT = WORKSPACE / "residency_app/.data/project-completion-private-run2/audit/1104430f67b74d5cb98979900677588f"


def make_active_clock(start, request_times):
    times = sorted(request_times)
    pauses = [(a, b) for a, b in zip(times, times[1:]) if b - a > 600]

    def active_hours(timestamp):
        elapsed_pauses = sum(min(end, timestamp) - begin for begin, end in pauses if begin < timestamp)
        return (timestamp - start - elapsed_pauses) / 3600

    return active_hours, pauses


def read_request_times():
    return [
        json.loads((directory / "request.json").read_text())["at"]
        for directory in AUDIT.iterdir() if directory.name.isdigit()
    ]
