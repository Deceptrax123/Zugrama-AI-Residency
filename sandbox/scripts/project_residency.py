"""Preview, enroll, or serve an idle skills/project residency on loopback 7381.

preview --manifest FILE is read-only. serve additionally requires that exact
manifest's SHA-256 with --confirm-manifest. enroll persists the same cohort and
closes without serving HTTP or starting memory/inference workers.
Pending residents are never enrolled.
Missing allowances must be configured unless a host-authorized time policy is present.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import sqlite3
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]

from residency.agent_tools import AgentTools
from residency.identity import rows
from residency.local_mem0 import AgentMem0
from residency.markdown_memory import write_private
from residency.project_experiment import ProjectCohort, manifest_digest, project_identity, validate_manifest
from residency.server import ResidencyServer
from runtime_settings import gateway_settings

DATA = ROOT / '.data/project-completion'


def time_policy():
    path = DATA / 'time-policy.json'
    if not path.exists():
        return None
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or set(value) != {'schema', 'duration_seconds', 'usd_allowances_enforced', 'authorization'}
            or value['schema'] not in ('project-persona-time/v1', 'project-persona-time/v2')
            or type(value['duration_seconds']) is not int or value['duration_seconds'] != 28800
            or value['usd_allowances_enforced'] is not False
            or not isinstance(value['authorization'], str) or not value['authorization'].strip()):
        raise ValueError('Use the explicitly authorized eight-hour persona policy; existing data preserved')
    return value


def run_policy():
    path = DATA / 'run-policy.json'
    if not path.exists():
        return {'schema': 'project-run-policy/v1', 'private_breakout_files': False, 'worker_supervision': False}
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or set(value) != {'schema', 'private_breakout_files', 'worker_supervision'}
            or value['schema'] != 'project-run-policy/v1'
            or any(type(value[k]) is not bool for k in ('private_breakout_files', 'worker_supervision'))):
        raise ValueError('Use an explicit project privacy and worker-supervision policy')
    return value


def environment():
    path = DATA / 'environment.json'
    if not path.exists():
        return {'schema': 'project-village-environment/v1', 'judges': [], 'world_tools_enabled': False}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or set(value) != {'schema', 'judges', 'world_tools_enabled'} or value['schema'] != 'project-village-environment/v1':
        raise ValueError('Unrecognized project environment; existing data preserved')
    if type(value['world_tools_enabled']) is not bool or not isinstance(value['judges'], list) or len(value['judges']) > 10:
        raise ValueError('Use bounded judge roles and an explicit tool-enabled choice')
    seen = set()
    for judge in value['judges']:
        if not isinstance(judge, dict) or set(judge) != {'name', 'existing_member_id', 'remit', 'skills', 'criteria'}:
            raise ValueError('Use only sourced skills and an assigned judge remit')
        if any(not isinstance(judge[k], str) or not judge[k].strip() or len(judge[k]) > (80 if k=='name' else 2000) for k in ('name', 'existing_member_id', 'remit', 'skills')):
            raise ValueError('Provide bounded judge name, source, remit and skills')
        if not isinstance(judge['criteria'], list) or not 1 <= len(judge['criteria']) <= 8 or any(not isinstance(c, str) or len(c)>500 for c in judge['criteria']):
            raise ValueError('Provide explicit bounded judging criteria')
        if judge['existing_member_id'] in seen:
            raise ValueError('Duplicate competition judge')
        seen.add(judge['existing_member_id'])
    return value


def known_members():
    path = ROOT / '.data/live-residency/state/residency.sqlite3'
    if not path.exists():
        return set()
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        return {r[0] for r in db.execute('SELECT member_id FROM agent_identities')}


def preview(manifest):
    validate_manifest(manifest)
    known = known_members()
    invalid = [p['name'] for p in manifest['residents']
               if p['enrollment'] == 'existing' and p['existing_member_id'] not in known]
    if invalid:
        raise ValueError('Existing resident mapping was not found: ' + ', '.join(invalid))
    included = [p for p in manifest['residents'] if p['enrollment'] != 'pending_approval']
    env = environment()
    timing = time_policy()
    if any(j['existing_member_id'] not in known for j in env['judges']):
        raise ValueError('A judge source is missing from the existing residency')
    if len(included) + len(env['judges']) > 50:
        raise ValueError('Competitors and judges together must fit the 50-participant capacity')
    if {j['existing_member_id'] for j in env['judges']} & {p.get('existing_member_id') for p in included}:
        raise ValueError('A judge cannot simultaneously be a project competitor')
    return {'manifest_sha256': manifest_digest(manifest), 'event_started': False,
            'model_calls': 0, 'residents_in_manifest': len(manifest['residents']),
            'eligible': [p['name'] for p in included],
            'pending_approval': [p['name'] for p in manifest['residents'] if p['enrollment'] == 'pending_approval'],
            'missing_allowances': [] if timing else [p['name'] for p in included if not p.get('budget')],
            'time_policy': timing,
            'run_policy': run_policy(),
            'judges': [j['name'] for j in env['judges']],
            'world_tools_enabled': env['world_tools_enabled'],
            'group_size_limit': len(included) + len(env['judges']), 'pair_only': False,
            'missing_judge_allowances': [] if timing else [j['name'] for j in env['judges']],
            'data_directory': str(DATA), 'url': 'http://127.0.0.1:7381'}


def prepare_server(manifest, confirmation, port=7381):
    summary = preview(manifest)
    if confirmation != summary['manifest_sha256']:
        raise ValueError('Review preview and confirm the exact manifest SHA-256 before enrollment')
    people = [p for p in manifest['residents'] if p['enrollment'] != 'pending_approval']
    env = environment()
    env_digest = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
    if len(people) < 2:
        raise ValueError('At least two approved or existing residents are needed')
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    setup_path = DATA / 'setup.json'
    if setup_path.exists():
        saved = json.loads(setup_path.read_text())
        if saved.get('kind') != 'residency-project-completion/v1' or saved.get('manifest_sha256') != confirmation:
            raise ValueError('Existing project-run data belongs to another manifest; it was preserved')
        if saved.get('environment_sha256') not in (None, env_digest):
            raise ValueError('The saved environment changed; review before reconfiguring an existing run')
    else:
        saved = {'kind': 'residency-project-completion/v1', 'manifest_sha256': confirmation,
                 'join_code': secrets.token_urlsafe(24), 'host_password': secrets.token_urlsafe(30)}
        write_private(setup_path, json.dumps(saved, indent=2))
    config = gateway_settings(DATA / 'state', saved['join_code'],
                              origin='http://127.0.0.1:7381', model='gpt-6.1-sol', reasoning_effort='high')
    server = ResidencyServer(('127.0.0.1', port), config)
    try:
        server.project_records = {}
        server.project_judges = {}
        server.project_lab_enabled = env['world_tools_enabled']
        server.project_private_rooms = summary['run_policy']['private_breakout_files']
        server.project_worker_supervision = summary['run_policy']['worker_supervision']
        server.project_time_limit_seconds = summary['time_policy']['duration_seconds'] if summary['time_policy'] else None
        server.bounded_context = True
        server.continue_existing_rooms = True
        server.audit_directory = DATA / 'audit'
        server.delegate_enabled = False
        server.allowance_transfers_enabled = False
        server.sandbox = ProjectCohort(server)
        if server.event and server.event.state.get('event_id') and saved.get('environment_sha256') is None and env['judges']:
            raise ValueError('Judge roles can only be added before the first project event')
        if not server.sandbox.owner:
            token, _ = server.sandbox.signup({'name': 'Project experiment host',
                'email': 'project-host@agent.invalid', 'password': saved['host_password'],
                'join_code': saved['join_code']})
            server.store.logout(token)
        owner = server.sandbox.owner
        current = {r['slot']: r for r in rows(server.store)}
        for slot, person in enumerate(people, 1):
            if slot not in current:
                server.sandbox.save_agent(owner, slot, project_identity(person))
                record = next(r for r in rows(server.store) if r['slot'] == slot)
                if person.get('budget'):
                    server.sandbox.accounts.configure(owner, {'owner_id': record['member_id'], **person['budget']})
                server.memory.set_policy(record['member_id'], {
                    'instructions': 'Remember project goals, skills, concrete contributions, blockers and evidence.',
                    'exclude_terms': [], 'capture_conversations': True, 'recall_enabled': True,
                    'network_context': False})
            else:
                record = current[slot]
            server.project_records[record['member_id']] = person
        for slot, judge in enumerate(env['judges'], len(people) + 1):
            identity = {'name': judge['name'], 'skills': judge['skills'], 'cv': judge['remit'],
                        'introduction': judge['name'] + ' — disclosed competition-judge NPC. ' + judge['remit']}
            if slot not in current:
                server.sandbox.save_agent(owner, slot, identity)
                record = next(r for r in rows(server.store) if r['slot'] == slot)
                server.memory.set_policy(record['member_id'], {'instructions': 'Remember project evidence, review feedback and next checks only.',
                    'exclude_terms': [], 'capture_conversations': True, 'recall_enabled': True, 'network_context': False})
            else:
                record = current[slot]
                if record['identity']['name'] != judge['name']:
                    raise ValueError('Existing slot does not match its assigned judge; data preserved')
            server.project_judges[record['member_id']] = {k: judge[k] for k in ('name', 'remit', 'criteria')}
        if server.project_lab_enabled:
            from residency.project_lab import ProjectTools
            server.agent_tools = ProjectTools(server)
        saved['environment_sha256'] = env_digest
        write_private(setup_path, json.dumps(saved, indent=2))
        return server, {**summary, 'enrolled_in_separate_database': len(people),
                        'competitors': len(people), 'judge_npcs': len(env['judges']),
                        'total_participants': len(people) + len(env['judges']),
                        'host_email': 'project-host@agent.invalid',
                        'host_password_file': str(setup_path)}
    except BaseException:
        server.server_close()
        raise


def enroll(manifest, confirmation):
    server, summary = prepare_server(manifest, confirmation, port=0)
    try:
        summary.update(event_status=server.event.state['status'],
                       enrolled_names=[r['identity']['name'] for r in rows(server.store)],
                       model_calls=server.event.state['calls'],
                       event_started=bool(server.event.state['event_id']))
        return summary
    finally:
        server.server_close()


def serve(manifest, confirmation, seed=None):
    server, summary = prepare_server(manifest, confirmation)
    server.event_seed = seed
    supervisor = None
    try:
        server.semantic = AgentMem0(server)
        if not getattr(server, 'agent_tools', None):
            server.agent_tools = AgentTools(server)
        if server.project_worker_supervision:
            from residency.project_supervisor import ProjectSupervisor
            supervisor = ProjectSupervisor(server)
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
        print(json.dumps(summary, indent=2), flush=True)
        server.serve_forever()
    finally:
        if supervisor:
            supervisor.close()
        server.server_close()


def main():
    global DATA
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('preview', 'enroll', 'serve'))
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--data-directory', type=Path)
    parser.add_argument('--confirm-manifest')
    parser.add_argument('--seed', type=int, help='Shuffle the order in which resident workers are launched')
    args = parser.parse_args()
    if args.seed is not None and args.command != 'serve':
        parser.error('--seed is only used with serve')
    if args.data_directory:
        DATA = args.data_directory.resolve()
    manifest = json.loads((args.manifest or DATA / 'manifest.json').read_text())
    if args.command == 'preview':
        print(json.dumps(preview(manifest), indent=2))
    else:
        os.umask(0o077)
        if args.command == 'enroll':
            print(json.dumps(enroll(manifest, args.confirm_manifest), indent=2))
        else:
            serve(manifest, args.confirm_manifest, args.seed)


if __name__ == '__main__':
    main()
