"""BEL's bounded tool proposals, local conversation journal, and verified undo.

The model has no executor reference. HTTP's existing exact-argument, one-use
owner grant remains the only route into execute(). No tool chains are automatic.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from .needle import NeedleRouter, NeedleError, normalize_tools
from .security import canonical, redact, TOKEN_PATTERN, atomic_private_write, safe_file
from .tools import StrictModel, FileWrite, DesktopAction, desktop_invoke
from .private_files import exclusive_file, snapshot, replace_content, delete_open_file


class FileMutationError(ValueError):
    """A side effect may have occurred; the preimage remains in the journal."""


class Empty(StrictModel):
    pass


class Application(StrictModel):
    application: Literal['notepad', 'calculator']


class FileEdit(FileWrite):
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class FileRename(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    destination: str = Field(min_length=1, max_length=100)
    expected_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Undo(StrictModel):
    undo_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class Invocation(StrictModel):
    executionId: str = Field(pattern=r'^[A-Za-z0-9_-]{8,100}$')
    taskId: str = Field(pattern=r'^[A-Za-z0-9_-]{8,100}$')
    tool: str = Field(pattern=r'^[a-z][a-z0-9_.]{1,79}$')
    arguments: dict = Field(default_factory=dict)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: type
    permissions: str
    risk: str = 'read'
    reversible: bool = False
    resources: tuple = ()
    timeout: int = 25

    def metadata(self):
        return {'name': self.name, 'description': self.description, 'version': '1',
                'input_schema': self.schema.model_json_schema(),
                'output_schema': {'type': 'object', 'required': ['status', 'tool', 'evidence'],
                                  'properties': {'status': {'enum': ['done', 'unverified', 'failed',
                                                                   'pending_confirmation', 'cancelled']},
                                                 'tool': {'type': 'string'}, 'evidence': {'type': 'object'}}},
                'permissions': [self.permissions], 'risk': self.risk, 'confirmation_required': True,
                'timeout': self.timeout, 'resources': list(self.resources), 'reversible': self.reversible,
                'undo_handler': 'files.undo' if self.reversible else None}


class Bel:
    def __init__(self, store, files, capabilities, needle=None):
        self.store, self.files, self.capabilities = store, files, capabilities
        self.needle = needle or NeedleRouter()
        self.lock = asyncio.Lock()
        self.tools = {t.name: t for t in [
            Tool('app.launch', 'Open or focus Notepad or Calculator', Application, 'desktop.explicit', 'high'),
            Tool('files.list', 'List filenames in BEL private workspace', Empty, 'sight.workspace.read'),
            Tool('files.create', 'Create a new text file in BEL private workspace', FileWrite,
                 'sight.workspace.create', 'reversible-write', True),
            Tool('files.edit', 'Replace a private text file after reviewing its current SHA256', FileEdit,
                 'sight.workspace.write', 'reversible-write', True),
            Tool('files.rename', 'Rename a private text file after reviewing its current SHA256', FileRename,
                 'sight.workspace.write', 'reversible-write', True),
            Tool('files.undo', 'Undo one verified private file operation', Undo, 'sight.workspace.write', 'reversible-write'),
        ]}
        for spec in capabilities.specs.values():
            if spec.available:
                self.tools[spec.id] = Tool(spec.id, spec.description.replace('SIGHT', 'BEL'), spec.schema,
                                           spec.permissions, spec.risk, resources=spec.dependencies)
        with store.connect() as db:
            # Separate extension version preserves legacy database readers and full backups.
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS bel_meta (key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            version = db.execute("SELECT value FROM bel_meta WHERE key='version'").fetchone()
            if version and version[0] != '1':
                raise ValueError('Unsupported BEL journal version')
            db.execute("INSERT OR IGNORE INTO bel_meta VALUES('version','1')")
            db.execute('CREATE TABLE IF NOT EXISTS bel_history (seq INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, at REAL NOT NULL, UNIQUE(request_id,role))')
            db.execute('CREATE TABLE IF NOT EXISTS bel_executions (id TEXT PRIMARY KEY, task TEXT NOT NULL, fingerprint TEXT NOT NULL, args TEXT NOT NULL, state TEXT NOT NULL, result TEXT, created REAL NOT NULL, UNIQUE(task,fingerprint))')
            db.execute('CREATE TABLE IF NOT EXISTS bel_undo (id TEXT PRIMARY KEY, operation TEXT NOT NULL, before_data TEXT NOT NULL, after_data TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL)')
            origin = str(store.path.parent.resolve())
            saved_origin = db.execute("SELECT value FROM bel_meta WHERE key='data_origin'").fetchone()
            if saved_origin and saved_origin[0] != origin:
                db.execute("UPDATE bel_undo SET state='unverified' WHERE state IN ('ready','prepared','undoing')")
                db.execute("UPDATE bel_executions SET state='unverified' WHERE state='running'")
            db.execute("INSERT INTO bel_meta VALUES('data_origin',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (origin,))

    def recover(self):
        with self.store.connect() as db:
            db.execute("UPDATE bel_executions SET state='unverified' WHERE state='running'")
            db.execute("UPDATE bel_undo SET state='unverified' WHERE state IN ('prepared','undoing')")

    def history_generation(self):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM bel_meta WHERE key='history_generation'").fetchone()
            return int(row[0]) if row else 0

    def remember(self, request_id, role, text, generation=None):
        if role not in {'user', 'assistant'}:
            raise ValueError('Invalid role')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM bel_meta WHERE key='history_generation'").fetchone()
            if generation is not None and generation != (int(row[0]) if row else 0):
                return
            db.execute('INSERT OR IGNORE INTO bel_history(request_id,role,text,at) VALUES(?,?,?,?)',
                       (request_id, role, redact(str(text))[:16000], time.time() * 1000))
            db.execute('DELETE FROM bel_history WHERE seq NOT IN (SELECT seq FROM bel_history ORDER BY seq DESC LIMIT 200)')

    def history(self):
        with self.store.connect() as db:
            rows = db.execute('SELECT seq,role,text,at FROM bel_history ORDER BY seq').fetchall()
        return {'items': [{'id': str(r['seq']), 'role': r['role'], 'text': r['text'], 'at': r['at']} for r in rows],
                'retention': {'max_messages': 200, 'scope': 'local', 'backups': 'Existing backups retain earlier history until the owner removes those backups.'}}

    def clear_history(self):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM bel_history')
            db.execute("INSERT INTO bel_meta VALUES('history_generation','1') ON CONFLICT(key) DO UPDATE SET value=CAST(value AS INTEGER)+1")
        return {'ok': True, 'status': 'done', 'scope': 'conversation history only; saved memories and existing backups retained'}

    def registry(self):
        return [t.metadata() for t in self.tools.values()]

    def select(self, text):
        words = set(re.findall(r'[a-z0-9]+', text.lower())) - {'the', 'a', 'an', 'to', 'please', 'bel', 'my', 'in', 'or', 'of', 'and', 'local', 'private', 'workspace'}
        aliases = {'file': 'files', 'folder': 'files', 'note': 'markdown', 'speak': 'speech',
                   'rename': 'files', 'notepad': 'app', 'calculator': 'app'}
        namespaces = {aliases[w] for w in words if w in aliases}
        ranked = []
        for tool in self.tools.values():
            # One unsupported nested schema must not disable all eligible tools.
            try:
                normalize_tools([{'name': tool.name, 'description': tool.description,
                                  'parameters': tool.schema.model_json_schema()}])
            except NeedleError:
                continue
            terms = set(re.findall(r'[a-z0-9]+', tool.name + ' ' + tool.description.lower()))
            name_terms = set(tool.name.split('.'))
            score = len(words & terms) + 3 * len(words & name_terms)
            if tool.name.split('.')[0] in namespaces:
                score += 8
            if score:
                ranked.append((score, tool))
        ranked.sort(key=lambda item: (-item[0], item[1].name))
        # A shared namespace alone must not flood a small model with conflicting
        # operations. Keep similarly relevant choices; unsupported/ambiguous
        # intent still goes through model validation and owner review.
        cutoff = max(1, ranked[0][0] * .8) if ranked else 1
        return [t for score, t in ranked[:6] if score >= cutoff]

    def normalize(self, args):
        value = Invocation.model_validate(args)
        tool = self.tools.get(value.tool)
        if not tool:
            raise ValueError('Tool unavailable')
        normalized = value.model_dump()
        normalized['arguments'] = tool.schema.model_validate(value.arguments).model_dump(mode='json')
        if TOKEN_PATTERN.search(canonical(normalized)):
            raise ValueError('Credentials are not tool arguments')
        if value.tool.startswith('files.'):
            for key in ('name', 'destination'):
                if key in normalized['arguments']:
                    self.files.path(normalized['arguments'][key])
        return normalized

    def validate(self, path, args):
        if path == '/api/bel/history/clear':
            return Empty.model_validate(args).model_dump(), 'Clear the local conversation history. Saved memories and existing backups remain.'
        if path != '/api/bel/tools/execute':
            return None
        normalized = self.normalize(args)
        tool = self.tools[normalized['tool']]
        description = tool.description
        if tool.name == 'files.undo':
            description = self.undo_preview(normalized['arguments']['undo_id'])
        return normalized, description + '. Permission: ' + tool.permissions + '. Review these exact arguments; one execution only.'

    async def propose(self, text, task_id):
        if re.sub(r'[^a-z ]', '', text.casefold()).strip().removeprefix('bel ').strip() == 'undo that':
            ready = next((item for item in self.undo_items() if item['state'] == 'ready'), None)
            if ready:
                args = self.normalize({'executionId': uuid.uuid4().hex, 'taskId': task_id,
                                       'tool': 'files.undo', 'arguments': {'undo_id': ready['id']}})
                return {'path': '/api/bel/tools/execute', 'args': args, 'tool': 'files.undo',
                        'summary': self.undo_preview(ready['id']),
                        'source': 'exact owner undo command and local journal'}
        selected = self.select(text)
        if not selected:
            return None
        functions = [{'type': 'function', 'function': {'name': t.name, 'description': t.description,
                       'parameters': t.schema.model_json_schema()}} for t in selected]
        result = await self.needle.propose(text, functions)
        if result.get('status') != 'proposed' or len(result.get('calls', [])) != 1:
            return None
        call = result['calls'][0]
        if call.get('name') not in {t.name for t in selected}:
            return None
        try:
            args = self.normalize({'executionId': uuid.uuid4().hex, 'taskId': task_id,
                                   'tool': call['name'], 'arguments': call['arguments']})
        except (ValueError, KeyError, TypeError):
            return None
        return {'path': '/api/bel/tools/execute', 'args': args, 'tool': args['tool'],
                'summary': self.tools[args['tool']].description, 'confidence': result.get('confidence')}

    def _begin(self, args):
        fingerprint = hashlib.sha256(canonical({'tool': args['tool'], 'arguments': args['arguments']}).encode()).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM bel_executions WHERE id=? OR (task=? AND fingerprint=?)',
                             (args['executionId'], args['taskId'], fingerprint)).fetchone()
            if row:
                if row['fingerprint'] != fingerprint or row['task'] != args['taskId']:
                    raise ValueError('Execution id conflicts with earlier action')
                return json.loads(row['result']) if row['result'] else {'status': 'unverified', 'tool': args['tool'],
                        'evidence': {'reason': 'Earlier attempt has no verified result; it will not be repeated.'}}
            if db.execute('SELECT count(*) FROM bel_executions WHERE task=?', (args['taskId'],)).fetchone()[0] >= 3:
                raise ValueError('Per-task execution budget exhausted')
            if args['tool'] == 'app.launch' and db.execute('SELECT 1 FROM bel_executions WHERE fingerprint=? AND created>?',
                                                          (fingerprint, time.time() - 10)).fetchone():
                raise ValueError('Duplicate application request within cooldown')
            db.execute("INSERT INTO bel_executions VALUES(?,?,?,?,'running',NULL,?)",
                       (args['executionId'], args['taskId'], fingerprint, canonical(redact(args)), time.time()))
        return None

    def _finish(self, args, result):
        result = redact(result)
        with self.store.connect() as db:
            db.execute('UPDATE bel_executions SET state=?,result=? WHERE id=?',
                       (result['status'], canonical(result), args['executionId']))
        self.store.event('bel.tool.finished', {'tool': args['tool'], 'status': result['status']}, args['taskId'])
        return result

    async def execute(self, args):
        args = self.normalize(args)
        if self.lock.locked():
            raise ValueError('A reviewed tool is already running')
        async with self.lock:
            previous = self._begin(args)
            if previous is not None:
                return previous | {'duplicate': True}
            self.store.event('bel.tool.started', {'tool': args['tool']}, args['taskId'])
            try:
                async with asyncio.timeout(self.tools[args['tool']].timeout):
                    result = await self._dispatch(args['tool'], args['arguments'])
            except asyncio.CancelledError:
                self._finish(args, {'status': 'unverified', 'tool': args['tool'],
                                   'evidence': {'reason': 'Cancelled during execution; inspect state before any new action.'}})
                raise
            except TimeoutError:
                result = {'status': 'unverified', 'tool': args['tool'], 'evidence': {'reason': 'Execution deadline exceeded; no automatic retry.'}}
            except FileMutationError:
                result = {'status': 'unverified', 'tool': args['tool'], 'evidence': {'reason': 'File operation interrupted or verification failed. Preserved preimage requires manual recovery; no automatic retry.'}}
            except Exception:
                result = {'status': 'failed', 'tool': args['tool'], 'evidence': {'reason': 'Tool failed or its prerequisites changed; no automatic retry.'}}
            return self._finish(args, result)

    async def _dispatch(self, name, args):
        if name == 'app.launch':
            result = await asyncio.to_thread(desktop_invoke, DesktopAction(action='app.launch', **args))
            return {'status': 'done' if result.get('gui_verified') else 'unverified', 'tool': name, 'evidence': result}
        if name == 'files.list':
            return {'status': 'done', 'tool': name, 'evidence': {'names': self.files.list()}}
        if name.startswith('files.') and name in {'files.create', 'files.edit', 'files.rename', 'files.undo'}:
            return self.file_action(name, args)
        value = await self.capabilities.invoke({'id': name, 'arguments': args})
        evidence = value['result']
        # Adapter completion is not a claim about external device or account effects.
        if artifact := evidence.get('artifact'):
            path = self.capabilities.artifacts.path(artifact['id'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
                raise ValueError('Artifact verification failed')
        return {'status': 'done', 'tool': name, 'evidence': evidence}

    def _snapshot(self, name):
        path = safe_file(self.files.path(name))
        stat = path.stat()
        if stat.st_size > 262144 or stat.st_nlink != 1:
            raise ValueError('File too large or linked')
        data = path.read_bytes()
        return {'name': name, 'content': data.decode('utf-8'), 'sha256': hashlib.sha256(data).hexdigest(),
                'identity': [stat.st_dev, stat.st_ino], 'size': stat.st_size}

    def undo_items(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM bel_undo ORDER BY created DESC LIMIT 50").fetchall()
        return [{'id': r['id'], 'operation': r['operation'], 'state': r['state'], 'created': r['created'],
                 'name': json.loads(r['after_data'])['name'],
                 'original_name': (json.loads(r['before_data']) or {}).get('name')}
                for r in rows]

    def undo_preview(self, identifier):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM bel_undo WHERE id=?', (identifier,)).fetchone()
        if not row or row['state'] != 'ready':
            raise ValueError('Undo unavailable or already consumed')
        before, after = json.loads(row['before_data']), json.loads(row['after_data'])
        name = json.dumps(after['name'], ensure_ascii=False)
        if row['operation'] == 'files.create':
            return 'Remove the unchanged file ' + name + ' created by BEL'
        if row['operation'] == 'files.edit':
            return 'Restore the saved previous content of ' + name
        return 'Rename ' + name + ' back to ' + json.dumps(before['name'], ensure_ascii=False)

    def file_action(self, tool, args):
        if tool == 'files.undo':
            return self._undo(args['undo_id'])
        source = self.files.path(args['name'])
        context = nullcontext(None) if tool == 'files.create' else exclusive_file(source)
        with context as stream:
            before = snapshot(stream, args['name']) if stream is not None else None
            if before and before['sha256'] != args['expected_sha256']:
                raise ValueError('File changed since preview')
            destination = args.get('destination', args['name'])
            if tool in {'files.create', 'files.rename'} and self.files.path(destination).exists():
                raise ValueError('Destination already exists')
            undo_id = uuid.uuid4().hex
            with self.store.connect() as db:
                db.execute("INSERT INTO bel_undo VALUES(?,?,?,?,'prepared',?)",
                           (undo_id, tool, canonical(before), canonical({'name': destination}), time.time()))
            try:
                if tool == 'files.create':
                    self.files.write_new(args['name'], args['content'])
                elif tool == 'files.edit':
                    replace_content(stream, args['content'])
                else:
                    self.files.write_new(destination, before['content'])
                    delete_open_file(stream)
                after = snapshot(stream, destination) if tool == 'files.edit' else self._snapshot(destination)
                expected = before['content'] if tool == 'files.rename' else args['content']
                if after['content'] != expected:
                    raise ValueError('File verification failed')
            except BaseException as exc:
                with self.store.connect() as db:
                    db.execute("UPDATE bel_undo SET state='unverified' WHERE id=?", (undo_id,))
                raise FileMutationError('Operation needs manual inspection') from exc
        if tool == 'files.rename' and source.exists():
            raise FileMutationError('Source removal unverified')
        with self.store.connect() as db:
            db.execute("UPDATE bel_undo SET after_data=?,state='ready' WHERE id=?", (canonical(after), undo_id))
        return {'status': 'done', 'tool': tool, 'evidence': {'name': destination, 'sha256': after['sha256'], 'undo_id': undo_id}}

    def _undo(self, identifier):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM bel_undo WHERE id=?', (identifier,)).fetchone()
            if not row or row['state'] != 'ready':
                raise ValueError('Undo unavailable or already consumed')
            before, after = json.loads(row['before_data']), json.loads(row['after_data'])
        with exclusive_file(safe_file(self.files.path(after['name']))) as stream:
            if snapshot(stream, after['name']) != after:
                raise ValueError('File changed since action; undo refused')
            if row['operation'] == 'files.rename' and self.files.path(before['name']).exists():
                raise ValueError('Original name is occupied')
            with self.store.connect() as db:
                cursor = db.execute("UPDATE bel_undo SET state='undoing' WHERE id=? AND state='ready'", (identifier,))
                if cursor.rowcount != 1:
                    raise ValueError('Undo already reserved')
            try:
                if row['operation'] == 'files.create':
                    delete_open_file(stream)
                elif row['operation'] == 'files.edit':
                    replace_content(stream, before['content'])
                else:
                    self.files.write_new(before['name'], before['content'])
                    delete_open_file(stream)
            except BaseException as exc:
                with self.store.connect() as db:
                    db.execute("UPDATE bel_undo SET state='unverified' WHERE id=?", (identifier,))
                raise FileMutationError('Undo needs manual inspection') from exc
        if row['operation'] == 'files.create':
            verified = not self.files.path(after['name']).exists()
        elif row['operation'] == 'files.edit':
            verified = self._snapshot(before['name'])['sha256'] == before['sha256']
        else:
            verified = self._snapshot(before['name'])['sha256'] == before['sha256'] and not self.files.path(after['name']).exists()
        with self.store.connect() as db:
            db.execute('UPDATE bel_undo SET state=? WHERE id=?', ('undone' if verified else 'unverified', identifier))
        return {'status': 'done' if verified else 'unverified', 'tool': 'files.undo', 'evidence': {'undo_id': identifier}}
