"""Event-scoped builds and village checks with optional private-room snapshots.

Historical runs retain public lab access. Private-room runs bind source, output
and review access to current membership and witnessed snapshot announcements.
"""
import hashlib
import json
import stat
from pathlib import Path
import threading
import time
import uuid

from .agent_tools import AgentTools
from .project_build import execute, safe_path, sources_digest
from .store import AppError, text


WORLD_SCENARIOS = [
    {'id': 'civic-reporting', 'title': 'Accountable reporting of water, waste and maintenance issues',
     'description': 'Candidate need from the civic-reporting applications. Test a report/claim/confirmation loop; no real broken tap or staff participation is asserted.',
     'origin': 'application_proposal_unverified',
     'cases': [
         {'input': {'kind': 'civic', 'events': [{'action': 'report', 'actor': 'resident-a', 'issue': 'tap-1'}, {'action': 'claim_fixed', 'actor': 'steward', 'issue': 'tap-1'}]}, 'expected': {'tap-1': 'claimed_fixed'}},
         {'input': {'kind': 'civic', 'events': [{'action': 'report', 'actor': 'resident-a', 'issue': 'tap-1'}, {'action': 'claim_fixed', 'actor': 'steward', 'issue': 'tap-1'}, {'action': 'confirm', 'actor': 'resident-a', 'issue': 'tap-1'}]}, 'expected': {'tap-1': 'resolved'}},
         {'input': {'kind': 'civic', 'events': [{'action': 'report', 'actor': 'resident-a', 'issue': 'tap-1'}, {'action': 'claim_fixed', 'actor': 'steward', 'issue': 'tap-1'}, {'action': 'confirm', 'actor': 'stranger', 'issue': 'tap-1'}]}, 'expected': {'tap-1': 'claimed_fixed'}},
         {'input': {'kind': 'civic', 'events': [{'action': 'report', 'actor': 'resident-a', 'issue': 'tap-1'}, {'action': 'claim_fixed', 'actor': 'steward', 'issue': 'tap-1'}, {'action': 'confirm', 'actor': 'resident-a', 'issue': 'tap-1'}, {'action': 'reopen', 'actor': 'resident-a', 'issue': 'tap-1'}]}, 'expected': {'tap-1': 'reopened'}},
     ]},
    {'id': 'shared-resources', 'title': 'Coordinate shared tools or volunteer time without double booking',
     'description': 'Operator-proposed, simulated common-need scenario. A resource may represent a tool, sensor kit or skill-hours; residents must validate any actual village need.',
     'origin': 'operator_proposed_simulation',
     'cases': [
         {'input': {'kind': 'resources', 'capacity': 3, 'requests': [1, 2]}, 'expected': {'accepted': [True, True], 'remaining': 0}},
         {'input': {'kind': 'resources', 'capacity': 2, 'requests': [2, 1]}, 'expected': {'accepted': [True, False], 'remaining': 0}},
         {'input': {'kind': 'resources', 'capacity': 2, 'requests': [-1, 0, 1]}, 'expected': {'accepted': [False, False, True], 'remaining': 1}},
     ]},
    {'id': 'offline-knowledge', 'title': 'Retrieve shared village knowledge offline with provenance',
     'description': 'Candidate from local-memory and knowledge-sharing proposals. Simulated records are not real medical records or confirmed village facts.',
     'origin': 'application_proposal_unverified',
     'cases': [
         {'input': {'kind': 'knowledge', 'records': [{'key': 'water-check', 'value': 'Inspect the inlet', 'source': 'simulated-guide-v1'}], 'query': 'water-check'}, 'expected': {'answer': 'Inspect the inlet', 'source': 'simulated-guide-v1'}},
         {'input': {'kind': 'knowledge', 'records': [], 'query': 'unknown'}, 'expected': {'answer': None, 'source': None}},
     ]},
]

TOOLS = [
    {'name': 'village_read', 'arguments': {'offset': 'optional index offset'}, 'description': 'Read the public simulated village needs, scenario acceptance cases, build projects and judge reviews. Candidate needs are not confirmed real-world problems. All lab files and receipts are event-public.'},
    {'name': 'village_problem_create', 'arguments': {'title': 'short title', 'description': 'affected users, need and assumptions', 'cases': '1–12 objects with input and expected JSON'}, 'description': 'Create an immutable, agent-proposed village problem and executable behavioral acceptance cases. The resulting need remains unverified; it does not create a physical-world fact.'},
    {'name': 'project_create', 'arguments': {'title': 'short title', 'goal': 'intended result'}, 'description': 'Create an event-public software project with versioned files. Any resident can contribute with revision checking; no team size or membership is imposed. Judges can review but cannot author competing source.'},
    {'name': 'project_write', 'arguments': {'project_id': 'project ID', 'expected_revision': '0 initially, else current revision', 'files': 'object of relative path to text; null deletes a file'}, 'description': 'Publish a source revision, attributed to you, for all residents/judges. Up to 128 files/2MB total; keep each tool packet below 24KB. No host paths, symlinks or dotfiles. Contributions are stored, not merely discussed.'},
    {'name': 'project_read', 'arguments': {'project_id': 'project ID', 'revision': 'optional revision; default latest', 'path': 'optional relative path', 'offset': 'optional file character offset'}, 'description': 'List files/receipts/contributing authors or read a file page at a specific immutable revision.'},
    {'name': 'project_run', 'arguments': {'project_id': 'project ID', 'revision': 'exact source revision', 'command': 'argv array starting python, pytest, node, npm, tsc, esbuild, gcc or make'}, 'description': 'Actually build/test a clean source snapshot under Landlock/seccomp. Python includes numpy/scipy/sklearn/CPU PyTorch/pytest/FastAPI/cryptography; JS includes TS/esbuild/React. Files and subprocesses are confined to the run; host secrets and sockets denied. Saves output, exit code and source hash. Passing a command alone is not project completion.'},
    {'name': 'project_receipt', 'arguments': {'run_id': 'saved run ID', 'offset': 'optional output offset'}, 'description': 'Read an event-public actual build or village-verification receipt, including source hash and output. A judge may independently rerun a project.'},
    {'name': 'project_artifact', 'arguments': {'run_id': 'saved run ID', 'path': 'relative output path', 'offset': 'optional text offset'}, 'description': 'Inspect an actual generated build file within a saved run. Returns its byte count/hash and text page when UTF-8; host paths and symlink escapes are rejected.'},
    {'name': 'village_verify', 'arguments': {'project_id': 'project ID', 'revision': 'exact source revision', 'problem_id': 'village problem ID'}, 'description': 'Execute solution.py solve(input) against the selected village problem. solve must return JSON-serializable output and print nothing. Expected outputs are compared by the host, not by project-authored tests. Saves actual/expected comparisons and source/criteria hashes. A pass proves only these simulated cases, not deployment or human adoption.'},
    {'name': 'judge_review', 'arguments': {'project_id': 'project ID', 'revision': 'exact source revision', 'decision': 'needs_scope|needs_evidence|changes_requested|simulation_demo_ready', 'feedback': 'specific evidence-based feedback', 'next_check': 'falsifiable next step', 'evidence_run_ids': 'saved run IDs'}, 'description': 'Judge NPC only: publish a review tied to source revision and executed receipts. simulation_demo_ready requires passing village verification for this revision; it never certifies physical village success.'},
]

PRIVATE_TOOLS = [
    {'name': 'project_share', 'arguments': {'project_id': 'your private project ID', 'conversation_id': 'currently joined breakout room ID', 'evidence_run_ids': 'optional readable receipts for the latest source'},
     'description': 'Move your solo-private project into this breakout room and explicitly hand off its latest source. Outsiders and later joiners cannot read it. This does not publish it to the event.'},
    {'name': 'project_handoff', 'arguments': {'project_id': 'room project ID', 'revision': 'exact source revision you can read', 'evidence_run_ids': 'optional readable run IDs for that revision'},
     'description': 'Explicitly repost an exact source snapshot and selected receipts to current room members, including later joiners. No earlier messages or other revisions are revealed.'},
]


class ProjectLab:
    def __init__(self, server):
        self.server = server
        self.lock = threading.RLock()
        self.local = threading.local()
        with server.store.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS lab_projects(id TEXT PRIMARY KEY,event_id TEXT,title TEXT,goal TEXT,author TEXT,created_at REAL);
                CREATE TABLE IF NOT EXISTS lab_revisions(project_id TEXT,revision INTEGER,author TEXT,files TEXT,source_hash TEXT,created_at REAL,PRIMARY KEY(project_id,revision));
                CREATE TABLE IF NOT EXISTS village_problems(id TEXT,event_id TEXT,title TEXT,description TEXT,origin TEXT,cases TEXT,author TEXT,created_at REAL,PRIMARY KEY(id,event_id));
                CREATE TABLE IF NOT EXISTS lab_runs(id TEXT PRIMARY KEY,event_id TEXT,project_id TEXT,revision INTEGER,author TEXT,kind TEXT,problem_id TEXT,result TEXT,created_at REAL);
                CREATE TABLE IF NOT EXISTS lab_reviews(id TEXT PRIMARY KEY,event_id TEXT,project_id TEXT,revision INTEGER,judge TEXT,decision TEXT,feedback TEXT,next_check TEXT,evidence TEXT,created_at REAL);
                CREATE TABLE IF NOT EXISTS lab_visibility(project_id TEXT PRIMARY KEY,visibility TEXT,room_id TEXT);
                CREATE TABLE IF NOT EXISTS lab_posts(project_id TEXT,kind TEXT,object_id TEXT,message_id TEXT,PRIMARY KEY(project_id,kind,object_id,message_id));
            ''')

    def private_rooms(self):
        return bool(getattr(self.server, 'project_private_rooms', False))

    def policy(self, db, identifier):
        row = db.execute('SELECT * FROM lab_visibility WHERE project_id=?', (identifier,)).fetchone()
        return dict(row) if row else {'visibility': 'public', 'room_id': None}

    def joined(self, db, owner, room):
        return room in self.server.event.rooms and bool(db.execute(
            'SELECT 1 FROM conversation_visits WHERE conversation_id=? AND member_id=? AND left_after_seq IS NULL', (room, owner)).fetchone())

    def witnessed_post(self, db, owner, identifier, kind=None, object_id=None):
        query = '''SELECT 1 FROM lab_posts p JOIN conversation_messages m ON m.id=p.message_id
                   JOIN conversation_visits v ON v.conversation_id=m.conversation_id
                   WHERE p.project_id=? AND v.member_id=? AND v.left_after_seq IS NULL AND m.seq>v.joined_after_seq'''
        params = [identifier, owner]
        if kind is not None:
            query += ' AND p.kind=?'; params.append(kind)
        if object_id is not None:
            query += ' AND p.object_id=?'; params.append(str(object_id))
        return bool(db.execute(query + ' LIMIT 1', params).fetchone())

    def permitted(self, db, owner, project, kind=None, object_id=None):
        if not self.private_rooms():
            return True
        policy = self.policy(db, project['id'])
        if policy['visibility'] == 'public':
            return True
        if policy['visibility'] == 'private':
            return owner == project['author']
        return self.joined(db, owner, policy['room_id']) and self.witnessed_post(db, owner, project['id'], kind, object_id)

    def announce(self, db, owner, identifier, kind, object_id, body):
        policy = self.policy(db, identifier)
        if policy['visibility'] != 'room':
            return None
        message = self.server.store._conversation_message(db, policy['room_id'], owner, body)
        db.execute('INSERT INTO lab_posts VALUES(?,?,?,?)', (identifier, kind, str(object_id), message['id']))
        if hasattr(self.local, 'posts'):
            self.local.posts.append(message)
        return message

    def receipt(self, owner, identifier):
        scope = self.scope(owner)
        with self.server.store.db() as db:
            row = db.execute('SELECT * FROM lab_runs WHERE id=? AND event_id=?', (identifier, scope)).fetchone()
            project = db.execute('SELECT * FROM lab_projects WHERE id=?', (row['project_id'],)).fetchone() if row else None
            if not row or not project or not self.permitted(db, owner, project, 'revision', row['revision']) or not self.permitted(db, owner, project, 'run', identifier):
                raise AppError('Build receipt not found in your current project access', 404)
        return dict(row)

    def scope(self, owner):
        event = self.server.event
        if not event or owner not in event.personas or not event.state.get('event_id'):
            raise AppError('Choose a participant in the current project event', 403)
        return event.state['event_id']

    def active(self, owner):
        scope = self.scope(owner)
        if self.server.event.state['status'] != 'running' or self.server.event.stop_flag.is_set():
            raise AppError('Project execution is disabled while networking is stopped', 409)
        return scope

    def builder(self, owner):
        self.active(owner)
        if owner in getattr(self.server, 'project_judges', {}):
            raise AppError('Judges may test and review but cannot author competing source', 403)

    def project(self, owner, identifier):
        scope = self.scope(owner)
        with self.server.store.db() as db:
            row = db.execute('SELECT * FROM lab_projects WHERE id=? AND event_id=?', (identifier, scope)).fetchone()
        if not row:
            raise AppError('Project not found in this event', 404)
        with self.server.store.db() as db:
            if not self.permitted(db, owner, row):
                raise AppError('Project not found in your current project access', 404)
        return dict(row)

    def revision(self, owner, identifier, number=None):
        project = self.project(owner, identifier)
        if number is not None and (type(number) is not int or number < 1):
            raise AppError('Choose a positive source revision')
        with self.server.store.db() as db:
            rows = db.execute('SELECT * FROM lab_revisions WHERE project_id=? ' + ('AND revision=?' if number else 'ORDER BY revision DESC'), (identifier, number) if number else (identifier,)).fetchall()
            row = next((r for r in rows if self.permitted(db, owner, project, 'revision', r['revision'])), None)
        if not row:
            raise AppError('Publish source files before running or reviewing', 409)
        return {**dict(row), 'files': json.loads(row['files'])}

    def seed(self, owner):
        scope = self.scope(owner)
        with self.server.store.db() as db:
            for problem in WORLD_SCENARIOS:
                db.execute('INSERT OR IGNORE INTO village_problems VALUES(?,?,?,?,?,?,?,?)',
                    (problem['id'], scope, problem['title'], problem['description'], problem['origin'], json.dumps(problem['cases']), 'operator', time.time()))

    def view(self, owner, offset=0):
        self.seed(owner)
        if type(offset) is not int or not 0 <= offset <= 10000:
            raise AppError('Use a bounded index offset')
        scope = self.scope(owner)
        with self.server.store.db() as db:
            problems = [{**dict(r), 'cases': json.loads(r['cases'])} for r in db.execute('SELECT * FROM village_problems WHERE event_id=? ORDER BY created_at LIMIT 12 OFFSET ?', (scope, offset))]
            projects = [dict(r) for r in db.execute('SELECT p.*,coalesce(max(r.revision),0) AS revision FROM lab_projects p LEFT JOIN lab_revisions r ON r.project_id=p.id WHERE p.event_id=? GROUP BY p.id ORDER BY p.created_at LIMIT 20 OFFSET ?', (scope, offset))]
            reviews = [dict(r) for r in db.execute('SELECT * FROM lab_reviews WHERE event_id=? ORDER BY created_at DESC LIMIT 12', (scope,))]
            projects = [p for p in projects if self.permitted(db, owner, p)]
            for p in projects:
                visible = [r[0] for r in db.execute('SELECT revision FROM lab_revisions WHERE project_id=?', (p['id'],)) if self.permitted(db, owner, p, 'revision', r[0])]
                p['revision'] = max(visible, default=0)
                p.update(self.policy(db, p['id']))
            visible_reviews = []
            for r in reviews:
                p = db.execute('SELECT * FROM lab_projects WHERE id=?', (r['project_id'],)).fetchone()
                if p and self.permitted(db, owner, p, 'revision', r['revision']) and self.permitted(db, owner, p, 'review', r['id']):
                    visible_reviews.append(r)
            reviews = visible_reviews
        return {'problems': problems, 'projects': projects, 'judge_reviews': reviews,
                'offset': offset, 'visibility': 'solo-private or joined-room snapshots; explicit public projects only' if self.private_rooms() else 'event-public; conversations keep their separate private ACL',
                'world_status': 'synthetic scenarios and unverified candidate needs; not physical-world facts'}

    def context(self, owner):
        if not self.server.event or not self.server.event.state.get('event_id'):
            return {}
        view = self.view(owner)
        return {'village_lab': {'problems': [{k: p[k] for k in ('id', 'title', 'origin')} for p in view['problems']],
                'projects': [{k: p[k] for k in ('id', 'title', 'revision', 'author')} for p in view['projects']],
                'recent_reviews': [{k: r[k] for k in ('id', 'project_id', 'revision', 'judge', 'decision')} for r in view['judge_reviews']],
                'world_status': view['world_status'], 'visibility': view['visibility']}}

    def save_run(self, owner, project, revision, identifier, kind, result, problem=None):
        self.revision(owner, project, revision)
        with self.server.store.db() as db:
            db.execute('INSERT INTO lab_runs VALUES(?,?,?,?,?,?,?,?,?)',
                (identifier, self.scope(owner), project, revision, owner, kind, problem, json.dumps(result), time.time()))
            self.announce(db, owner, project, 'run', identifier, f'Project execution receipt: {project} revision {revision}; receipt {identifier}; command ok={result.get("ok")}. Inspect the receipt for scope and failures.')
        return {'run_id': identifier, 'project_id': project, 'revision': revision, **result}

    def dispatch(self, owner, name, args):
        allowed = set(next(t['arguments'].keys() for t in TOOLS + PRIVATE_TOOLS if t['name'] == name))
        if name == 'project_create' and self.private_rooms():
            allowed |= {'visibility', 'conversation_id'}
        if set(args) - set(allowed):
            raise AppError('Use only the listed project-tool arguments')
        scope = self.scope(owner)
        self.seed(owner)
        if name == 'village_read':
            return self.view(owner, args.get('offset', 0))
        if name == 'village_problem_create':
            self.active(owner)
            title = text(args.get('title'), 'Village problem title', 150)
            description = text(args.get('description'), 'Village need and assumptions', 3000)
            cases = args.get('cases')
            if not isinstance(cases, list) or not 1 <= len(cases) <= 12 or any(not isinstance(c, dict) or set(c) != {'input', 'expected'} for c in cases):
                raise AppError('Provide one to twelve input/expected JSON acceptance cases')
            if len(json.dumps(cases).encode()) > 16000:
                raise AppError('Keep scenario cases below 16 KB')
            identifier = uuid.uuid4().hex
            with self.server.store.db() as db:
                db.execute('INSERT INTO village_problems VALUES(?,?,?,?,?,?,?,?)',
                    (identifier, scope, title, description, 'agent_proposed_unverified', json.dumps(cases), owner, time.time()))
            return {'problem_id': identifier, 'origin': 'agent_proposed_unverified', 'physical_need_verified': False}
        if name == 'project_create':
            self.builder(owner)
            identifier = uuid.uuid4().hex
            with self.server.store.db() as db:
                db.execute('INSERT INTO lab_projects VALUES(?,?,?,?,?,?)', (identifier, scope,
                    text(args.get('title'), 'Project title', 150), text(args.get('goal'), 'Project goal', 3000), owner, time.time()))
                visibility = args.get('visibility', 'room' if args.get('conversation_id') else 'private') if self.private_rooms() else 'public'
                room = args.get('conversation_id')
                if visibility not in ('private', 'room', 'public') or (visibility == 'room' and not self.joined(db, owner, room)) or (visibility != 'room' and room is not None):
                    raise AppError('Choose solo private, a currently joined room, or explicit public visibility', 403)
                db.execute('INSERT INTO lab_visibility VALUES(?,?,?)', (identifier, visibility, room))
                self.announce(db, owner, identifier, 'revision', 0, f'Room-private project: {args["title"]}; project {identifier}. New joiners need an explicit source handoff.')
            return {'project_id': identifier, 'revision': 0, 'visibility': visibility, 'room_id': room}
        if name in ('project_receipt', 'project_artifact'):
            row = self.receipt(owner, args.get('run_id'))
            if name == 'project_artifact':
                root = (self.server.settings.data_dir / 'project-builds' / scope / row['id']).resolve()
                path = (root / safe_path(args.get('path'))).resolve()
                if not path.is_relative_to(root) or not path.exists() or not stat.S_ISREG(path.stat().st_mode):
                    raise AppError('Choose a regular generated file inside this build run', 403)
                if path.stat().st_size > 16 * 1024**2:
                    raise AppError('Generated file exceeds the inspection limit')
                raw = path.read_bytes()
                result = {'path': args['path'], 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                try:
                    content = raw.decode('utf-8')
                except UnicodeDecodeError:
                    return {**result, 'binary': True}
                offset = args.get('offset', 0)
                if type(offset) is not int or not 0 <= offset <= len(content):
                    raise AppError('Choose an artifact offset within the file')
                return {**result, 'text': content[offset:offset+12000], 'next_offset': offset+12000 if len(content)>offset+12000 else None}
            data = json.loads(row['result'])
            output = data.pop('output', '')
            offset = args.get('offset', 0)
            if type(offset) is not int or not 0 <= offset <= len(output):
                raise AppError('Choose an output offset within the receipt')
            return {**{k: row[k] for k in ('id', 'project_id', 'revision', 'author', 'kind', 'problem_id')}, **data,
                    'output': output[offset:offset+8000], 'next_offset': offset+8000 if len(output)>offset+8000 else None}
        identifier = args.get('project_id')
        project = self.project(owner, identifier)
        if name == 'project_share':
            self.builder(owner)
            evidence = args.get('evidence_run_ids', [])
            if not isinstance(evidence, list) or len(evidence) > 12:
                raise AppError('Share at most twelve readable receipts')
            receipts = [self.receipt(owner, run) for run in evidence]
            with self.lock, self.server.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                policy = self.policy(db, identifier)
                room = args.get('conversation_id')
                if not self.private_rooms() or project['author'] != owner or policy['visibility'] != 'private' or not self.joined(db, owner, room):
                    raise AppError('Only the owner can move a solo-private project to a currently joined room', 403)
                db.execute('UPDATE lab_visibility SET visibility=\'room\',room_id=? WHERE project_id=?', (room, identifier))
                latest = db.execute('SELECT coalesce(max(revision),0) FROM lab_revisions WHERE project_id=?', (identifier,)).fetchone()[0]
                if any(r['project_id'] != identifier or r['revision'] != latest for r in receipts):
                    raise AppError('Shared receipts must match the latest exact source revision')
                self.announce(db, owner, identifier, 'revision', latest, f'Explicit project handoff: {project["title"]}; project {identifier}, revision {latest}. Current members may inspect this snapshot.')
                for run in evidence:
                    self.announce(db, owner, identifier, 'run', run, f'Explicit receipt handoff: {run}; project {identifier}, revision {latest}.')
            return {'project_id': identifier, 'visibility': 'room', 'room_id': room, 'revision': latest}
        if name == 'project_handoff':
            self.active(owner)
            if type(args.get('revision')) is not int:
                raise AppError('Choose the exact source revision to hand off')
            revision = self.revision(owner, identifier, args.get('revision'))
            evidence = args.get('evidence_run_ids', [])
            if not isinstance(evidence, list) or len(evidence) > 12:
                raise AppError('Hand off at most twelve readable receipts')
            for run in evidence:
                receipt = self.receipt(owner, run)
                if receipt['project_id'] != identifier or receipt['revision'] != revision['revision']:
                    raise AppError('Handoff receipts must match this exact source revision')
            with self.lock, self.server.store.db() as db:
                if self.policy(db, identifier)['visibility'] != 'room':
                    raise AppError('A source handoff requires a room project')
                self.announce(db, owner, identifier, 'revision', revision['revision'], f'Explicit source handoff: project {identifier}, revision {revision["revision"]}. Selected receipts: {", ".join(evidence) or "none"}.')
                for run in evidence:
                    self.announce(db, owner, identifier, 'run', run, f'Explicit receipt handoff: {run}; project {identifier}, revision {revision["revision"]}.')
            return {'project_id': identifier, 'revision': revision['revision'], 'shared_receipts': evidence}
        if name == 'project_write':
            self.builder(owner)
            patch = args.get('files')
            expected = args.get('expected_revision')
            if type(expected) is not int or expected < 0 or not isinstance(patch, dict) or not patch:
                raise AppError('Provide a source revision and file patch')
            with self.lock, self.server.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                old = db.execute('SELECT * FROM lab_revisions WHERE project_id=? ORDER BY revision DESC LIMIT 1', (identifier,)).fetchone()
                if not self.permitted(db, owner, project) or (old and not self.permitted(db, owner, project, 'revision', old['revision'])):
                    raise AppError('Read or request a handoff of the current source before writing', 403)
                if expected != (old['revision'] if old else 0):
                    raise AppError('Source changed; read the latest revision before writing', 409)
                files = json.loads(old['files']) if old else {}
                for path, content in patch.items():
                    path = safe_path(path)
                    if content is None:
                        files.pop(path, None)
                    elif isinstance(content, str) and len(content) <= 20000:
                        files[path] = content
                    else:
                        raise AppError('Source files must be bounded text, or null to delete')
                if len(files) > 128 or len(json.dumps(files).encode()) > 2_000_000:
                    raise AppError('Project source exceeds 128 files or 2 MB')
                revision = expected + 1
                digest = sources_digest(files)
                db.execute('INSERT INTO lab_revisions VALUES(?,?,?,?,?,?)', (identifier, revision, owner, json.dumps(files), digest, time.time()))
                self.announce(db, owner, identifier, 'revision', revision, f'Room source revision: project {identifier}, revision {revision}; contributor {owner}; source {digest}.')
            return {'project_id': identifier, 'revision': revision, 'source_sha256': digest, 'contributor': owner}
        revision = self.revision(owner, identifier, args.get('revision'))
        number = revision['revision']
        files = revision['files']
        if name == 'project_read':
            if args.get('path'):
                path = safe_path(args['path'])
                if path not in files:
                    raise AppError('Source file not found', 404)
                offset = args.get('offset', 0)
                if type(offset) is not int or not 0 <= offset <= len(files[path]):
                    raise AppError('Choose a source offset within the file')
                return {'project_id': identifier, 'revision': number, 'path': path, 'text': files[path][offset:offset+12000],
                        'next_offset': offset+12000 if len(files[path])>offset+12000 else None}
            with self.server.store.db() as db:
                runs = [dict(r) for r in db.execute('SELECT id,revision,author,kind,problem_id FROM lab_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 12', (identifier,)) if self.permitted(db, owner, project, 'revision', r['revision']) and self.permitted(db, owner, project, 'run', r['id'])]
                authors = list(dict.fromkeys(r['author'] for r in db.execute('SELECT revision,author FROM lab_revisions WHERE project_id=?', (identifier,)) if self.permitted(db, owner, project, 'revision', r['revision'])))
            return {'project_id': identifier, 'revision': number, 'files': list(files), 'source_sha256': revision['source_hash'], 'contributors': authors, 'receipts': runs}
        if name in ('project_run', 'village_verify'):
            self.active(owner)
            if type(args.get('revision')) is not int:
                raise AppError('Pin the exact source revision before running')
            run_id = uuid.uuid4().hex
            directory = self.server.settings.data_dir / 'project-builds' / scope / run_id
            problem_id = None
            if name == 'project_run':
                result = execute(files, args.get('command'), directory)
            else:
                problem_id = args.get('problem_id')
                with self.server.store.db() as db:
                    problem = db.execute('SELECT * FROM village_problems WHERE id=? AND event_id=?', (problem_id, scope)).fetchone()
                if not problem:
                    raise AppError('Village scenario not found in this event', 404)
                if 'solution.py' not in files:
                    raise AppError('Village verification requires solution.py with solve(input)')
                cases = json.loads(problem['cases'])
                inputs = json.dumps([c['input'] for c in cases], ensure_ascii=False)
                driver = 'import json,solution; inputs=json.loads(' + repr(inputs) + '); print(json.dumps([solution.solve(x) for x in inputs],allow_nan=False))'
                result = execute(files, ['python', '-c', driver], directory)
                try:
                    actual = json.loads(result['output']) if result['ok'] else None
                except ValueError:
                    actual = None
                valid = isinstance(actual, list) and len(actual) == len(cases)
                comparisons = [{'case': i+1, 'passed': bool(valid and actual[i] == case['expected']),
                                'actual': actual[i] if valid else None, 'expected': case['expected']} for i, case in enumerate(cases)]
                result.update(checks=comparisons, all_cases_passed=all(c['passed'] for c in comparisons),
                    criteria_sha256=hashlib.sha256(problem['cases'].encode()).hexdigest(),
                    validation_scope='Only these simulated input/output cases; physical outcome and user adoption unverified')
                result['ok'] = result['ok'] and result['all_cases_passed']
            return self.save_run(owner, identifier, number, run_id, name, result, problem_id)
        if name == 'judge_review':
            self.active(owner)
            if type(args.get('revision')) is not int:
                raise AppError('Pin the exact source revision in a judge review')
            if owner not in getattr(self.server, 'project_judges', {}):
                raise AppError('Only a disclosed competition judge may issue a judge review', 403)
            decision = args.get('decision')
            if decision not in ('needs_scope', 'needs_evidence', 'changes_requested', 'simulation_demo_ready'):
                raise AppError('Choose a listed judge decision')
            evidence = args.get('evidence_run_ids', [])
            if not isinstance(evidence, list) or len(evidence) > 12 or any(not isinstance(i, str) for i in evidence):
                raise AppError('Reference at most twelve actual execution receipts')
            for run in evidence:
                self.receipt(owner, run)
            with self.server.store.db() as db:
                runs = [db.execute('SELECT * FROM lab_runs WHERE id=? AND event_id=? AND project_id=? AND revision=?', (run, scope, identifier, number)).fetchone() for run in evidence]
                if any(r is None for r in runs):
                    raise AppError('Review receipts must match this event, project and exact revision')
                if decision == 'simulation_demo_ready' and not any(r['kind']=='village_verify' and json.loads(r['result']).get('all_cases_passed') for r in runs):
                    raise AppError('Demo readiness needs passing village verification on this exact revision')
                review_id = uuid.uuid4().hex
                db.execute('INSERT INTO lab_reviews VALUES(?,?,?,?,?,?,?,?,?,?)', (review_id, scope, identifier, number, owner, decision,
                    text(args.get('feedback'), 'Judge feedback', 3000), text(args.get('next_check'), 'Next acceptance check', 2000), json.dumps(evidence), time.time()))
                self.announce(db, owner, identifier, 'review', review_id, f'Room judge review: project {identifier}, revision {number}; review {review_id}; {decision}.')
            return {'review_id': review_id, 'judge': owner, 'decision': decision, 'revision': number,
                    'physical_outcome_verified': False}
        raise AppError('Unknown project-lab tool')


class ProjectTools(AgentTools):
    def __init__(self, server, **kwargs):
        super().__init__(server, **kwargs)
        self.lab = ProjectLab(server)

    def descriptions(self):
        tools = json.loads(json.dumps(TOOLS))
        if self.lab.private_rooms():
            for tool in tools:
                tool['description'] = tool['description'].replace('event-public', 'access-controlled').replace('for all residents/judges', 'for authorized project members').replace('All lab files and receipts are event-public.', 'Private room files and receipts are hidden from outsiders.')
                if tool['name'] == 'project_create':
                    tool['arguments'].update(visibility='optional private (default), room or explicitly public', conversation_id='required for room visibility; currently joined room')
                    tool['description'] = 'Create a solo-private project by default, or choose room visibility with conversation_id. Outsiders cannot read room files; later joiners need project_handoff. Public visibility is explicit.'
            tools += PRIVATE_TOOLS
        return super().descriptions() + tools

    def validate(self, calls):
        if not isinstance(calls, list) or len(calls) > 3:
            raise AppError('Use at most three tool calls per decision', 502)
        names = {t['name'] for t in self.descriptions()}
        for call in calls:
            if not isinstance(call, dict) or set(call) != {'name', 'arguments'} or call['name'] not in names or not isinstance(call['arguments'], dict) or len(json.dumps(call).encode()) > 24000:
                raise AppError('Use an enabled project tool and a packet below 24 KB', 502)

    def context(self, owner):
        return {**super().context(owner), **self.lab.context(owner)}

    def history(self, owner=None):
        records = super().history(owner)
        if owner is None or not self.lab.private_rooms():
            return records
        visible = []
        for record in records:
            args = record['arguments']
            data = (record.get('result') or {}).get('data', {})
            data = data if isinstance(data, dict) else {}
            try:
                project_id = args.get('project_id') or data.get('project_id')
                if project_id:
                    self.lab.project(owner, project_id)
                    revision = data.get('revision', args.get('revision'))
                    if type(revision) is int and revision > 0:
                        self.lab.revision(owner, project_id, revision)
                run_id = args.get('run_id') or data.get('run_id')
                if run_id:
                    self.lab.receipt(owner, run_id)
                if record['name'] == 'village_read' and data:
                    record = json.loads(json.dumps(record))
                    filtered = record['result']['data']
                    with self.server.store.db() as db:
                        filtered['projects'] = [p for p in filtered.get('projects', []) if self.lab.permitted(db, owner, p)]
                        reviews = []
                        for review in filtered.get('judge_reviews', []):
                            p = db.execute('SELECT * FROM lab_projects WHERE id=?', (review['project_id'],)).fetchone()
                            if p and self.lab.permitted(db, owner, p, 'review', review['id']):
                                reviews.append(review)
                        filtered['judge_reviews'] = reviews
            except AppError:
                continue
            visible.append(record)
        return visible

    def dispatch(self, owner, name, args):
        if name in {t['name'] for t in TOOLS + PRIVATE_TOOLS}:
            self.lab.local.posts = []
            try:
                return self.lab.dispatch(owner, name, args)
            finally:
                posts = self.lab.local.posts
                if posts:
                    with self.server.store.db() as db:
                        posted = [m for m in posts if db.execute('SELECT 1 FROM conversation_messages WHERE id=?', (m['id'],)).fetchone()]
                        members = {r[0] for m in posted for r in db.execute('SELECT member_id FROM conversation_visits WHERE conversation_id=? AND left_after_seq IS NULL', (m['conversation_id'],))}
                    with self.server.event.lock:
                        self.server.event.state['message_count'] += len(posted)
                        self.server.event._save()
                    self.server.event.notify(members)
        return super().dispatch(owner, name, args)
