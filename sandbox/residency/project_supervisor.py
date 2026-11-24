"""Bounded repair of rejected decisions; persistent/uncertain errors freeze time."""
import json
import threading
import time

from .markdown_memory import write_private


class ProjectSupervisor:
    def __init__(self, server, cooldown=5, interval=1):
        self.server, self.cooldown, self.interval = server, cooldown, interval
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self.run, name='project-worker-supervisor', daemon=True)
        self.thread.start()

    def close(self):
        self.closed.set()
        self.thread.join(2)

    def tick(self):
        event = self.server.event
        if not event:
            return
        with event.lock:
            if event.state['status'] != 'paused_worker_error' or event.active or any(t.is_alive() for t in event.threads):
                return
            errors = event.state.get('agent_errors', {})
            history = event.state.get('worker_failure_history', [])
            latest = {r['member_id']: r for r in history}
            counts = event.state.setdefault('worker_repair_counts', {})
            safe = bool(errors) and all(latest.get(member, {}).get('safe_new_decision') and counts.get(member, 0) < 3 for member in errors)
            if not safe:
                event.state['error'] = 'Worker needs host diagnosis; active-time clock remains paused. No uncertain action was replayed.'
                event._save()
                write_private(event.directory / 'worker-attention.json', json.dumps({
                    'event_id': event.state['event_id'], 'at': time.time(),
                    'status': 'host_repair_required', 'errors': errors, 'clock_paused': True}, indent=2))
                return
            if time.time() - max(latest[m]['at'] for m in errors) < self.cooldown:
                return
            # A new decision gets a new call ID. Completed actions and tools are
            # never replayed by this supervisor; quota pauses are never resumed.
            for member in errors:
                counts[member] = counts.get(member, 0) + 1
            event._save()
            event.resume(event.host_id)

    def run(self):
        while not self.closed.wait(self.interval):
            try:
                self.tick()
            except Exception:
                # Keep the event paused on unexpected supervisor failures.
                event = self.server.event
                if event:
                    write_private(event.directory / 'worker-attention.json', json.dumps({
                        'event_id': event.state.get('event_id'), 'at': time.time(),
                        'status': 'supervisor_repair_required', 'clock_paused': event.state['status'] != 'running'}))
