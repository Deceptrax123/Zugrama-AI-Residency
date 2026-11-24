"""Run a seeded sandbox check with four made-up residents and local replies."""

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import random
import sys
from tempfile import TemporaryDirectory, mkdtemp
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from residency.config import APP_ROOT, Settings
from residency.local_mem0 import AgentMem0
from residency.project_experiment import ProjectCohort
from residency.project_lab import ProjectTools
from residency.server import ResidencyServer


class ScriptedGateway:
    def __init__(self, peers):
        self.peers = peers

    def check(self):
        return None

    def request(self, path, payload=None, headers=None, *, timeout=None):
        if path == '/health':
            return {'residency_budget_guard': 'residency-usd-v1'}
        if path != '/v1/chat/completions':
            raise ValueError(f'Unexpected gateway request: {path}')
        context = json.loads(payload['messages'][-1]['content'])
        resident = context['member_id']
        chosen = self.peers[resident]
        action = {
            'wait_seconds': 0,
            'start_conversations': [{'with': chosen, 'body': 'Can we check this example together?'}],
            'join_conversations': [], 'messages': [], 'leave_conversations': [],
            'budget_choice': 'end',
        }
        action['tool_calls'] = [{'name': 'project_create', 'arguments': {
            'title': f"Example by {context['persona']['name']}",
            'goal': 'Save a draft that a peer can review.',
        }}]
        return {
            'choices': [{'message': {'content': json.dumps(action)}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
        }


def run(directory, seed):
    config = Settings(data_dir=directory / 'state', join_code='local-check-invitation', hermes_model='gpt-6.1-sol')
    gateway = ScriptedGateway({})
    with ResidencyServer(('127.0.0.1', 0), config, hermes=gateway) as server:
        server.event_seed = seed
        server.audit_directory = directory / 'audit'
        server.continue_existing_rooms = True
        server.project_records = {}
        server.project_lab_enabled = True
        server.sandbox = ProjectCohort(server)
        server.agent_tools = ProjectTools(server)
        server.semantic = AgentMem0(server, SimpleNamespace(health=lambda: {'status': 'ready'}))
        cohort = server.sandbox
        token, _ = cohort.signup({'name': 'Sandbox check host', 'email': 'host@example.test',
                                  'password': 'sandbox check password', 'join_code': config.join_code})
        server.store.logout(token)
        names = {}
        for slot in range(1, 5):
            name = f'Resident {slot}'
            status = cohort.save_agent(cohort.owner, slot, {'name': name, 'skills': 'Review examples',
                                                            'introduction': f'{name} can help with examples.'})
            member = status['agents'][-1]['member_id']
            names[member] = name
            cohort.accounts.configure(cohort.owner, {'owner_id': member, 'limit_usd': '10', 'reserve_usd': '1'})
            server.memory.set_policy(member, {'capture_conversations': False, 'network_context': False})

        members = list(names)
        random.Random(seed).shuffle(members)
        for i, member in enumerate(members):
            gateway.peers[member] = [members[(i + offset) % len(members)]
                                     for offset in range(1, 3)]
        cohort.start(cohort.owner, {'npc_enabled': False})
        for worker in server.event.threads:
            worker.join(timeout=10)
        state = server.event.state
        if state['status'] != 'completed' or state['completed_calls'] != len(members):
            raise RuntimeError('Sandbox check failed. Review the event state and audit files.')

        with server.store.db() as db:
            conversations = []
            for room in db.execute('SELECT id, created_by FROM conversations'):
                peers = [names[row['member_id']] for row in db.execute(
                    'SELECT member_id FROM conversation_visits WHERE conversation_id=? AND member_id<>?',
                    (room['id'], room['created_by']))]
                conversations.append({'from': names[room['created_by']], 'to': sorted(peers)})
            messages = db.execute('SELECT count(*) FROM conversation_messages').fetchone()[0]
            drafts = [row['title'] for row in db.execute('SELECT title FROM lab_projects ORDER BY title')]
            tool_receipts = db.execute("SELECT count(*) FROM agent_tool_runs WHERE status='completed'").fetchone()[0]

        expected = [{'from': names[member], 'to': sorted(names[peer] for peer in peers)}
                    for member, peers in gateway.peers.items()]
        if sorted(conversations, key=lambda room: room['from']) != sorted(expected, key=lambda room: room['from']):
            raise RuntimeError('Saved conversations do not match the seeded choices.')
        if messages != len(members) or len(drafts) != len(members) or tool_receipts != len(drafts):
            raise RuntimeError('The saved message, project, or tool counts differ from the check.')
        return {'mode': 'projects', 'seed': seed, 'completed_calls': state['completed_calls'],
                'worker_launch_order': [names[member] for member in state['worker_launch_order']],
                'messages': messages, 'conversations': sorted(conversations, key=lambda room: room['from']),
                'project_drafts': drafts, 'tool_receipts': tool_receipts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=int, required=True)
    parser.add_argument('--keep', action='store_true', help='Keep the database and raw audit files')
    args = parser.parse_args()
    parent = APP_ROOT / '.data' / 'sandbox-checks'
    parent.mkdir(parents=True, exist_ok=True)
    options = {'prefix': f'projects-{args.seed}-', 'dir': parent}
    run_directory = nullcontext(mkdtemp(**options)) if args.keep else TemporaryDirectory(**options)
    with run_directory as directory:
        if args.keep:
            print(f'Run files: {directory}', file=sys.stderr)
        result = run(Path(directory), args.seed)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
