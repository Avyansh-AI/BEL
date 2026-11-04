import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from sight_core.bel import Bel
from sight_core.capabilities import Capabilities
from sight_core.store import Store, restore_backup
from sight_core.tools import LocalFiles


@pytest.fixture
def bel(tmp_path):
    store = Store(tmp_path / 'data')
    files = LocalFiles(tmp_path / 'data/files')
    return Bel(store, files, Capabilities(store, files))


def call(tool, arguments, execution='execute-0001', task='task-0001'):
    return dict(executionId=execution, taskId=task, tool=tool, arguments=arguments)


def invoke(bel, tool, arguments, **kw):
    return asyncio.run(bel.execute(call(tool, arguments, **kw)))


def test_history_bounded_persistent_redacted(bel):
    for n in range(210):
        bel.remember(str(n), 'user', 'message ' + str(n))
    bel.remember('last', 'assistant', 'api_key=sk-' + 'a' * 40)
    bel.remember('last', 'assistant', 'duplicate ignored')
    restored = Bel(bel.store, bel.files, bel.capabilities)
    history = restored.history()['items']
    assert len(history) == 200
    assert 'a' * 40 not in json.dumps(history)
    assert 'duplicate ignored' not in json.dumps(history)
    assert history[0]['text'] == 'message 11'


def test_create_undo_persists_and_refuses_replay(bel):
    result = invoke(bel, 'files.create', {'name': 'hello.txt', 'content': 'hello\nworld'})
    assert result['status'] == 'done'
    assert (bel.files.root / 'hello.txt').read_bytes() == b'hello\nworld'
    undo_id = result['evidence']['undo_id']
    restored = Bel(bel.store, bel.files, bel.capabilities)
    undone = invoke(restored, 'files.undo', {'undo_id': undo_id}, execution='execute-0002')
    assert undone['status'] == 'done'
    assert not (bel.files.root / 'hello.txt').exists()
    assert invoke(restored, 'files.undo', {'undo_id': undo_id}, execution='execute-0003', task='task-0002')['status'] == 'failed'


@pytest.mark.parametrize('action', ['files.edit', 'files.rename'])
def test_edit_rename_and_undo_preserve_original_bytes(bel, action):
    original = 'Original\r\nहिन्दी text\n'
    bel.files.write_new('before.txt', original)
    args = {'name': 'before.txt', 'expected_sha256': hashlib.sha256(original.encode()).hexdigest()}
    args.update({'content': 'New\ntext'} if action == 'files.edit' else {'destination': 'after.txt'})
    result = invoke(bel, action, args)
    assert result['status'] == 'done'
    undo = invoke(bel, 'files.undo', {'undo_id': result['evidence']['undo_id']}, execution='execute-0002')
    assert undo['status'] == 'done'
    assert (bel.files.root / 'before.txt').read_bytes() == original.encode()
    assert not (bel.files.root / 'after.txt').exists()


def test_undo_refuses_changed_or_replaced_file(bel):
    result = invoke(bel, 'files.create', {'name': 'hello.txt', 'content': 'hello'})
    (bel.files.root / 'hello.txt').write_text('owner edit')
    undo = invoke(bel, 'files.undo', {'undo_id': result['evidence']['undo_id']}, execution='execute-0002')
    assert undo['status'] == 'failed'
    assert (bel.files.root / 'hello.txt').read_text() == 'owner edit'


def test_rename_undo_refuses_occupied_original(bel):
    bel.files.write_new('old.txt', 'data')
    result = invoke(bel, 'files.rename', {'name': 'old.txt', 'destination': 'new.txt',
                    'expected_sha256': hashlib.sha256(b'data').hexdigest()})
    bel.files.write_new('old.txt', 'other')
    assert invoke(bel, 'files.undo', {'undo_id': result['evidence']['undo_id']}, execution='execute-0002')['status'] == 'failed'
    assert (bel.files.root / 'old.txt').read_text() == 'other'
    assert (bel.files.root / 'new.txt').read_text() == 'data'


@pytest.mark.parametrize('operation', ['files.create', 'files.edit', 'files.rename'])
def test_undo_review_identifies_effect_without_exposing_saved_contents(bel, operation):
    args = {'name': 'before.txt', 'content': 'private new text'}
    if operation != 'files.create':
        bel.files.write_new('before.txt', 'private original text')
        args['expected_sha256'] = hashlib.sha256(b'private original text').hexdigest()
    if operation == 'files.rename':
        args.pop('content')
        args['destination'] = 'after.txt'
    result = invoke(bel, operation, args)
    identifier = result['evidence']['undo_id']
    items = bel.undo_items()
    assert items[0]['name'] == ('after.txt' if operation == 'files.rename' else 'before.txt')
    assert 'private original text' not in json.dumps(items)
    _, summary = bel.validate('/api/bel/tools/execute', call('files.undo', {'undo_id': identifier}))
    assert 'before.txt' in summary
    assert 'private original text' not in summary
    if operation == 'files.rename':
        assert 'after.txt' in summary and 'Rename' in summary
    elif operation == 'files.create':
        assert 'Remove' in summary
    else:
        assert 'Restore' in summary


def test_duplicate_approval_never_reexecutes(bel):
    result = invoke(bel, 'files.create', {'name': 'single.txt', 'content': 'once'})
    again = invoke(bel, 'files.create', {'name': 'single.txt', 'content': 'once'}, execution='execute-0002')
    assert again == result | {'duplicate': True}
    assert len(bel.undo_items()) == 1
    with pytest.raises(ValueError, match='conflicts'):
        invoke(bel, 'files.create', {'name': 'other.txt', 'content': 'different'})


def test_budget_persists_across_restart(bel):
    for n in range(3):
        assert invoke(bel, 'files.create', {'name': f'{n}.txt', 'content': ''}, execution=f'execute-{n:04}')['status'] == 'done'
    restarted = Bel(bel.store, bel.files, bel.capabilities)
    with pytest.raises(ValueError, match='budget'):
        invoke(restarted, 'files.list', {}, execution='execute-0004')


def test_interrupted_execution_never_retries(bel):
    args = call('files.create', {'name': 'never.txt', 'content': 'x'})
    assert bel._begin(args) is None
    bel.recover()
    result = asyncio.run(bel.execute(args))
    assert result['status'] == 'unverified' and result['duplicate']
    assert not (bel.files.root / 'never.txt').exists()


def test_full_database_backup_preserves_bel_extension(bel, tmp_path):
    bel.remember('example', 'user', 'Keep my history')
    invoke(bel, 'files.list', {})
    backup = tmp_path / 'backup.sqlite3'
    bel.store.backup(backup)
    restore_backup(backup, tmp_path / 'restored')
    store = Store(tmp_path / 'restored')
    files = LocalFiles(tmp_path / 'restored/files')
    restored = Bel(store, files, Capabilities(store, files))
    assert restored.history()['items'][0]['text'] == 'Keep my history'
    assert invoke(restored, 'files.list', {})['duplicate']


def test_artifact_verified_after_adapter(bel):
    result = invoke(bel, 'documents.markdown', {'title': 'Review', 'text': 'Local only'})
    assert result['status'] == 'done'
    evidence = result['evidence']['artifact']
    assert bel.capabilities.artifacts.path(evidence['id']).read_text().startswith('# Review')


def test_launch_pid_alone_is_unverified(bel, monkeypatch):
    monkeypatch.setattr('sight_core.bel.desktop_invoke', lambda _: {'pid': 123, 'gui_verified': False})
    assert invoke(bel, 'app.launch', {'application': 'notepad'})['status'] == 'unverified'


def test_model_cannot_grant_itself_permission(bel):
    with pytest.raises(ValueError):
        bel.normalize(call('files.create', {'name': 'no.txt', 'content': 'x', 'confirmed': True}))
    with pytest.raises(ValueError):
        bel.normalize(call('shell.exec', {'command': 'anything'}))
    with pytest.raises(ValueError):
        bel.normalize(call('files.create', {'name': '../escape.txt', 'content': 'x'}))


def test_proposal_never_executes_and_revalidates(bel):
    class Needle:
        async def propose(self, text, tools):
            return {'status': 'proposed', 'confidence': .95, 'calls': [{'name': 'app.launch', 'arguments': {'application': 'notepad'}}]}
    bel.needle = Needle()
    proposal = asyncio.run(bel.propose('Open Notepad', 'task-0001'))
    assert proposal['path'] == '/api/bel/tools/execute'
    with bel.store.connect() as db:
        assert db.execute('SELECT count(*) FROM bel_executions').fetchone()[0] == 0
    class Invalid:
        async def propose(self, text, tools):
            return {'status': 'proposed', 'calls': [{'name': 'app.launch', 'arguments': {'application': 'powershell'}}]}
    bel.needle = Invalid()
    assert asyncio.run(bel.propose('Open Notepad', 'task-0001')) is None


def test_review_api_enforces_grant_and_history_clear(client, app):
    args = call('files.create', {'name': 'approved.txt', 'content': 'reviewed'})
    path = '/api/bel/tools/execute'
    assert client.post(path, json=args).status_code == 403
    review = client.post('/api/actions/prepare', json={'path': path, 'args': args}).json()
    payload = review['args'] | {'actionApproval': review['approvalId']}
    assert client.post(path, json=payload).json()['status'] == 'done'
    assert client.post(path, json=payload).status_code == 403
    app.state.bel.remember('test', 'user', 'preserved until approval')
    clear = '/api/bel/history/clear'
    assert client.post(clear, json={}).status_code == 403
    approval = client.post('/api/actions/prepare', json={'path': clear, 'args': {}}).json()
    assert client.post(clear, json={'actionApproval': approval['approvalId']}).status_code == 200
    assert client.get('/api/bel/history').json()['items'] == []


def test_bel_chat_ws_history_and_no_duplicate_model_request(client, app):
    class Needle:
        async def propose(self, *_):
            return {'status': 'fallback'}
    app.state.bel.needle = Needle()
    ticket = client.post('/api/access/ticket', json={}).json()['ticket']
    with client.websocket_connect('ws://127.0.0.1:8080/ws/app?ticket=' + ticket, headers={'origin': 'http://127.0.0.1:8080'}) as ws:
        assert ws.receive_json()['product'] == 'BEL'
        body = {'text': 'help', 'requestId': 'bel-chat-0001'}
        reply = client.post('/api/bel/chat', json=body).json()
        assert reply['status'] == 'ok' and 'BEL' in reply['say']
        assert ws.receive_json()['state'] == 'thinking'
        assert ws.receive_json()['state'] == 'task_completed'
        assert ws.receive_json()['state'] == 'offline'
        assert client.post('/api/bel/chat', json=body).json() == reply
    assert [r['role'] for r in client.get('/api/bel/history').json()['items']] == ['user', 'assistant']


def test_bel_provider_status_does_not_change_policy_or_usage(client, app):
    app.state.store.set_setting('usage.groq.example', {'requests': 3})
    result = client.get('/api/bel/providers').json()
    assert len(result['items']) == 3
    assert all(not r['policy']['enabled'] and r['policy']['daily_budget_usd'] == 0 for r in result['items'])
    assert app.state.store.setting('usage.groq.example')['requests'] == 3


def test_history_clear_blocks_late_response_from_old_turn(bel):
    generation = bel.history_generation()
    bel.remember('pending', 'user', 'old request', generation)
    bel.clear_history()
    bel.remember('pending', 'assistant', 'late response', generation)
    assert bel.history()['items'] == []
    bel.remember('new', 'user', 'new request', bel.history_generation())
    assert bel.history()['items'][0]['text'] == 'new request'


def test_selection_excludes_in_app_reminders_for_application_launch(bel):
    assert [t.name for t in bel.select('Open Notepad')] == ['app.launch']
    assert [t.name for t in bel.select('Open Calculator')] == ['app.launch']
    from sight_core.needle import normalize_tools
    selected = bel.select('Create a file named hello.txt containing Hello')
    assert 'files.create' in [t.name for t in selected]
    for tool in selected:
        normalize_tools([{'name': tool.name, 'description': tool.description,
                          'parameters': tool.schema.model_json_schema()}])


def test_tool_result_survives_model_summary_failure(client, app, monkeypatch):
    async def broken(*a, **kw):
        raise RuntimeError('Model disconnected')
    monkeypatch.setattr(app.state.router, 'generate', broken)
    args = call('files.create', {'name': 'completed.txt', 'content': 'done'})
    path = '/api/bel/tools/execute'
    review = client.post('/api/actions/prepare', json={'path': path, 'args': args}).json()
    response = client.post(path, json=review['args'] | {'actionApproval': review['approvalId']})
    assert response.status_code == 200 and response.json()['status'] == 'done'
    assert 'done' in response.json()['say']


def test_edit_excludes_concurrent_owner_write_during_journal_commit(bel, monkeypatch):
    from contextlib import contextmanager
    bel.files.write_new('locked.txt', 'before')
    connect = bel.store.connect
    blocked = []
    @contextmanager
    def interleaved():
        with connect() as db:
            yield db
            try:
                (bel.files.root / 'locked.txt').write_text('concurrent owner edit')
            except OSError:
                blocked.append(True)
    monkeypatch.setattr(bel.store, 'connect', interleaved)
    # Test the mutation directly so the attempted external writer is only inserted
    # at the actual preimage journal transaction, while the native handle is held.
    result = bel.file_action('files.edit', {'name': 'locked.txt', 'content': 'after',
                             'expected_sha256': hashlib.sha256(b'before').hexdigest()})
    assert result['status'] == 'done' and blocked


def test_partial_rename_is_unverified_and_preimage_retained(bel, monkeypatch):
    bel.files.write_new('old.txt', 'before')
    def fail(_):
        raise OSError('simulated removal failure after destination creation')
    monkeypatch.setattr('sight_core.bel.delete_open_file', fail)
    result = invoke(bel, 'files.rename', {'name': 'old.txt', 'destination': 'new.txt',
                                        'expected_sha256': hashlib.sha256(b'before').hexdigest()})
    assert result['status'] == 'unverified'
    assert (bel.files.root / 'new.txt').read_text() == 'before'
    assert (bel.files.root / 'old.txt').read_text() == 'before'
    assert bel.undo_items()[0]['state'] == 'unverified'


def test_restored_undo_is_explicitly_unverified(bel, tmp_path):
    invoke(bel, 'files.create', {'name': 'hello.txt', 'content': 'hello'})
    backup = tmp_path / 'with-undo.sqlite3'
    bel.store.backup(backup)
    restore_backup(backup, tmp_path / 'restore-undo')
    store = Store(tmp_path / 'restore-undo')
    files = LocalFiles(tmp_path / 'restore-undo/files')
    restored = Bel(store, files, Capabilities(store, files))
    assert restored.undo_items()[0]['state'] == 'unverified'


def test_natural_undo_proposes_latest_verified_action_without_execution(bel):
    assert asyncio.run(bel.propose('BEL, undo that.', 'undo-task-001')) is None
    made = invoke(bel, 'files.create', {'name': 'keep.txt', 'content': 'still here'})
    proposal = asyncio.run(bel.propose('BEL, undo that.', 'undo-task-001'))
    assert proposal['args']['arguments']['undo_id'] == made['evidence']['undo_id']
    assert (bel.files.root / 'keep.txt').read_text() == 'still here'
