import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import uuid

from fastapi.testclient import TestClient
import pytest

from sight_core.api import create_app
from sight_core.config import Config
from sight_core.local_speech import SpeechBusy, SpeechUnavailable, SpeechInputError

URL = 'http://127.0.0.1:8080'
BODY = {'audio': base64.b64encode(b'synthetic audio fixture').decode(), 'mimeType': 'audio/wav'}
RESPONSE = {'text': 'Open Notepad', 'confidence': .4, 'locale': 'en-US', 'engine': 'fixture', 'review_required': True}


def authenticate(client, app):
    client.post('/api/session/claim', json={'token': app.state.bootstrap_token}, headers={'origin': URL}).raise_for_status()
    client.headers['x-sight-csrf'] = client.get('/api/session').json()['csrf']


class Recognizer:
    calls = 0
    async def status(self):
        return {'available': True, 'locales': ['en-US'], 'reason': 'Synthetic recognizer fixture'}
    async def transcribe(self, raw, locale):
        self.calls += 1
        return dict(RESPONSE)


@pytest.fixture
def enabled(tmp_path):
    app = create_app(Config(tmp_path / 'data', local_stt=True))
    app.state.speech = Recognizer()
    with TestClient(app, base_url=URL) as client:
        authenticate(client, app)
        yield app, client


def test_disabled_configuration_keeps_microphone_policy_closed(client):
    assert 'microphone=()' in client.get('/').headers['permissions-policy']
    assert client.post('/api/speech/consent', json={'enabled': True}).status_code == 503
    assert client.post('/api/speech/transcribe', json=BODY).status_code == 503


def test_audio_requires_session_consent_and_csrf(enabled):
    app, client = enabled
    assert 'microphone=(self)' in client.get('/').headers['permissions-policy']
    assert 'microphone=()' in client.get('/legacy/').headers['permissions-policy']
    assert client.post('/api/speech/transcribe', json=BODY).status_code == 403
    assert client.post('/api/speech/consent', json={'enabled': True}, headers={'x-sight-csrf': 'invalid'}).status_code == 403
    assert client.post('/api/speech/consent', json={'enabled': 'true'}).status_code == 422
    assert app.state.speech.calls == 0
    assert client.post('/api/speech/consent', json={'enabled': True}).json() == {'enabled': True}
    assert client.get('/api/bel/status').json()['voice']['microphone_enabled']
    assert client.post('/api/speech/transcribe', json=BODY).json() == RESPONSE
    assert not client.get('/api/bel/history').json()['items']
    assert not client.get('/api/tools/files').json()['items']
    with app.state.store.connect() as db:
        assert db.execute('SELECT count(*) FROM bel_executions').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM requests').fetchone()[0] == 0
    assert b'Open Notepad' not in (app.state.config.data_dir / 'events.log').read_bytes()
    assert client.post('/api/speech/consent', json={'enabled': False}).json() == {'enabled': False}
    assert client.post('/api/speech/transcribe', json=BODY).status_code == 403


def test_consent_is_bound_to_exact_owner_session(enabled):
    app, first = enabled
    first.post('/api/speech/consent', json={'enabled': True}).raise_for_status()
    with TestClient(app, base_url=URL) as second:
        authenticate(second, app)
        assert second.post('/api/speech/transcribe', json=BODY).status_code == 403
        assert not second.get('/api/bel/status').json()['voice']['microphone_enabled']
        assert first.post('/api/speech/transcribe', json=BODY).status_code == 200


def test_cancel_before_upload_and_replay_never_start_another_worker(enabled):
    app, client = enabled
    client.post('/api/speech/consent', json={'enabled': True}).raise_for_status()
    cancelled = {'requestId': str(uuid.uuid4())}
    assert client.post('/api/speech/cancel', json=cancelled).json() == {'cancelled': True}
    assert client.post('/api/speech/transcribe', json={**BODY, **cancelled}).status_code == 409
    assert app.state.speech.calls == 0
    accepted = {'requestId': str(uuid.uuid4())}
    assert client.post('/api/speech/transcribe', json={**BODY, **accepted}).status_code == 200
    assert client.post('/api/speech/transcribe', json={**BODY, **accepted}).status_code == 409
    assert app.state.speech.calls == 1


def test_cancel_is_scoped_to_session_and_rejects_unbounded_ids(enabled):
    app, first = enabled
    first.post('/api/speech/consent', json={'enabled': True}).raise_for_status()
    identifier = {'requestId': str(uuid.uuid4())}
    with TestClient(app, base_url=URL) as second:
        authenticate(second, app)
        assert second.post('/api/speech/cancel', json=identifier).status_code == 200
        assert first.post('/api/speech/transcribe', json={**BODY, **identifier}).status_code == 200
        assert second.post('/api/speech/cancel', json={'requestId': 'x' * 2000}).status_code == 422
        assert second.post('/api/speech/cancel', json=identifier, headers={'x-sight-csrf': 'wrong'}).status_code == 403


@pytest.mark.parametrize('ignore_cancel', [False, True])
def test_stop_cancels_only_named_request_and_discards_late_results(enabled, ignore_cancel):
    app, client = enabled
    began, stopped = threading.Event(), threading.Event()
    class Pending(Recognizer):
        async def transcribe(self, raw, locale):
            began.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                if ignore_cancel:
                    return dict(RESPONSE)
                raise
            finally:
                stopped.set()
    app.state.speech = Pending()
    client.post('/api/speech/consent', json={'enabled': True}).raise_for_status()
    identifier = {'requestId': str(uuid.uuid4())}
    with ThreadPoolExecutor() as pool:
        request = pool.submit(client.post, '/api/speech/transcribe', json={**BODY, **identifier})
        assert began.wait(3)
        assert client.post('/api/speech/cancel', json={'requestId': str(uuid.uuid4())}).status_code == 200
        assert not stopped.is_set()
        assert client.post('/api/speech/cancel', json=identifier).status_code == 200
        result = request.result(timeout=5)
    assert stopped.is_set() and result.status_code == 409
    assert 'Open Notepad' not in result.text
    assert client.get('/api/bel/status').json()['voice']['microphone_enabled']


def test_request_record_capacity_fails_closed(enabled):
    _, client = enabled
    client.post('/api/speech/consent', json={'enabled': True}).raise_for_status()
    identifiers = [{'requestId': str(uuid.uuid4())} for _ in range(512)]
    for identifier in identifiers:
        assert client.post('/api/speech/cancel', json=identifier).status_code == 200
    assert client.post('/api/speech/cancel', json={'requestId': str(uuid.uuid4())}).status_code == 429
    assert client.post('/api/speech/transcribe', json={**BODY, **identifiers[0]}).status_code == 409
    assert client.post('/api/speech/transcribe', json=BODY).status_code == 429


@pytest.mark.parametrize('ignore_cancel', [False, True])
def test_revocation_cancels_and_discards_pending_transcripts(enabled, ignore_cancel):
    app, client = enabled
    began, stopped = threading.Event(), threading.Event()
    class Pending(Recognizer):
        async def transcribe(self, raw, locale):
            began.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                if ignore_cancel:
                    return dict(RESPONSE)
                raise
            finally:
                stopped.set()
    app.state.speech = Pending()
    client.post('/api/speech/consent', json={'enabled': True}).raise_for_status()
    with ThreadPoolExecutor() as pool:
        request = pool.submit(client.post, '/api/speech/transcribe', json=BODY)
        assert began.wait(3)
        assert client.post('/api/speech/transcribe', json=BODY).status_code == 429
        client.post('/api/speech/consent', json={'enabled': False}).raise_for_status()
        result = request.result(timeout=5)
    assert result.status_code == (403 if ignore_cancel else 409)
    assert stopped.is_set() and 'Open Notepad' not in result.text
    assert not client.get('/api/bel/history').json()['items']


@pytest.mark.parametrize('error,code', [(SpeechInputError, 422), (SpeechBusy, 429), (SpeechUnavailable, 503)])
def test_worker_failures_are_structured_and_do_not_echo_audio(enabled, error, code):
    app, client = enabled
    class Failed(Recognizer):
        async def transcribe(self, *_):
            raise error('private input must never be logged')
    app.state.speech = Failed()
    client.post('/api/speech/consent', json={'enabled': True}).raise_for_status()
    response = client.post('/api/speech/transcribe', json=BODY)
    assert response.status_code == code
    assert 'private input' not in response.text


def test_local_speech_environment_is_explicit_and_defaults_off(tmp_path, monkeypatch):
    monkeypatch.setenv('BEL_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('BEL_LOCAL_STT', raising=False)
    monkeypatch.delenv('SIGHT_LOCAL_STT', raising=False)
    assert not Config.from_env().local_stt
    monkeypatch.setenv('BEL_LOCAL_STT', 'windows')
    assert Config.from_env().local_stt
    monkeypatch.setenv('BEL_LOCAL_STT', 'maybe')
    with pytest.raises(ValueError, match='BEL_LOCAL_STT'):
        Config.from_env()
