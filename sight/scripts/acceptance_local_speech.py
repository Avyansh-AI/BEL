"""Live loopback HTTP acceptance using prerecorded synthetic WAVs, never a microphone.

Supply a private fixture directory containing voice-result.json and synthetic-N.wav.
The manifest's expected text is used only for grading, never passed to recognition.
Raw transcripts remain in the checkout's ignored cache; public evidence is aggregate.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import socket
import sqlite3
import sys
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sight_core.config import Config
from sight_core.desktop import BackendHost
from sight_core.windows_apps import WindowsBackend


def words(text):
    return re.findall(r"\w+", text.casefold())


def distance(expected, observed):
    previous = list(range(len(observed) + 1))
    for i, left in enumerate(expected, 1):
        current = [i]
        for j, right in enumerate(observed, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (left != right)))
        previous = current
    return previous[-1]


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def owned_speech_processes(inspector):
    """Observe only this harness's direct PowerShell children; never terminate them."""
    snapshot = inspector.kernel.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise RuntimeError('Process inspection unavailable')
    found = set()
    try:
        entry = inspector.entry_type()
        entry.dwSize = ctypes.sizeof(entry)
        if not inspector.kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise RuntimeError('Process inspection failed')
        while True:
            if entry.th32ParentProcessID == os.getpid() and entry.szExeFile.casefold() == 'powershell.exe':
                found.add(int(entry.th32ProcessID))
            if not inspector.kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                if ctypes.get_last_error() != 18:
                    raise RuntimeError('Process inspection incomplete')
                break
        return found
    finally:
        inspector.kernel.CloseHandle(snapshot)


def wait_speech_process(inspector, previous, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observed = owned_speech_processes(inspector) - previous
        if observed:
            return observed
        time.sleep(.005)
    return set()


def wait_process_exit(inspector, observed, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not observed.intersection(owned_speech_processes(inspector)):
            return True
        time.sleep(.01)
    return False


def verify(fixtures):
    cases = json.loads((fixtures / 'voice-result.json').read_text(encoding='utf-8-sig'))['cases']
    if not cases or any(not isinstance(case.get('expected'), str) for case in cases):
        raise ValueError('Expected an existing synthetic fixture manifest')
    samples = [(case, (fixtures / f"synthetic-{case['number']}.wav").read_bytes()) for case in cases]
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    cache = ROOT.parent / '.cache' / ('live-speech-' + run_id)
    cache.mkdir(parents=True)
    data = cache / 'data'
    config = Config(data, port=free_port(), local_stt=True)
    host = BackendHost(config)
    rows, raw_rows, metrics = [], [], []
    started = time.monotonic()
    result = {'format': 1, 'kind': 'Real Windows System.Speech over authenticated loopback HTTP',
              'run_id': run_id, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'platform': platform.platform(), 'python': platform.python_version(),
              'microphone_access': False, 'audible_playback': False,
              'cloud_inference_requests': 0, 'speech_input': 'Existing SAPI synthetic PCM WAV fixtures',
              'grammar': 'Unconstrained DictationGrammar; expected phrases never sent to recognizer',
              'source_sha256': {name: hashlib.sha256((ROOT / 'sight_core' / name).read_bytes()).hexdigest()
                                for name in ['api.py', 'config.py', 'local_speech.py', 'speech_worker.py']},
              'checks': rows, 'recognition': metrics,
              'limitations': ['Synthetic audio is not validation of a human voice, accent or physical microphone.',
                              'This harness does not validate browser capture, native permission prompts or audio devices.',
                              'Recognition quality is measured separately from protocol and permission acceptance.',
                              'No wake-word detector or Hindi recognizer is installed by this test.']}

    def check(name, passed, **details):
        rows.append({'id': name, 'passed': bool(passed), **details})

    def body(raw, locale='en-US', request_id=None):
        return {'audio': base64.b64encode(raw).decode('ascii'), 'mimeType': 'audio/wav',
                'locale': locale, 'requestId': request_id or str(uuid.uuid4())}

    try:
        launch = host.start()
        origin, token = launch.split('/#sight-session=', 1)
        check('backend_started', host.thread.is_alive())
        with httpx.Client(base_url=origin, timeout=35, trust_env=False) as client:
            check('unauthenticated_audio_rejected', client.post('/api/speech/transcribe', json=body(samples[0][1])).status_code == 401)
            claim = client.post('/api/session/claim', json={'token': token}, headers={'origin': origin})
            claim.raise_for_status()
            client.headers['x-sight-csrf'] = client.get('/api/session').json()['csrf']
            status = client.get('/api/speech').json()
            result['installed_locales'] = status['stt']['locales']
            check('real_english_recognizer_available', status['stt']['configured'] and 'en-US' in status['stt']['locales'])
            check('consent_defaults_off_and_wake_unavailable', not status['micEnabled'] and not status['wake']['enabled'])
            check('no_consent_no_recognition', client.post('/api/speech/transcribe', json=body(samples[0][1])).status_code == 403)
            check('consent_requires_csrf', client.post('/api/speech/consent', json={'enabled': True}, headers={'x-sight-csrf': 'invalid'}).status_code == 403)
            allowed = client.post('/api/speech/consent', json={'enabled': True})
            check('explicit_session_consent', allowed.status_code == 200 and allowed.json() == {'enabled': True})
            allowed.raise_for_status()
            cancelled_id = str(uuid.uuid4())
            cancelled = client.post('/api/speech/cancel', json={'requestId': cancelled_id})
            check('cancel_before_delayed_upload', cancelled.status_code == 200 and
                  client.post('/api/speech/transcribe', json=body(samples[0][1], request_id=cancelled_id)).status_code == 409)
            with httpx.Client(base_url=origin, timeout=35, trust_env=False) as other:
                other.post('/api/session/claim', json={'token': token}, headers={'origin': origin}).raise_for_status()
                other.headers['x-sight-csrf'] = other.get('/api/session').json()['csrf']
                check('consent_not_shared_between_sessions', other.post('/api/speech/transcribe', json=body(samples[0][1])).status_code == 403)
            check('malformed_wav_rejected', client.post('/api/speech/transcribe', json=body(b'RIFFbad')).status_code == 422)
            if 'hi-IN' not in status['stt']['locales']:
                unsupported = client.post('/api/speech/transcribe', json=body(samples[0][1], 'hi-IN'))
                check('absent_hindi_recognizer_reported', unsupported.status_code == 503, status_code=unsupported.status_code)
            for case, raw in samples:
                before = time.monotonic()
                request_body = body(raw)
                response = client.post('/api/speech/transcribe', json=request_body)
                elapsed = round(time.monotonic() - before, 3)
                heard = response.json()
                valid = (response.status_code == 200 and isinstance(heard.get('text'), str)
                         and bool(heard['text'].strip()) and heard.get('review_required') is True
                         and heard.get('engine') == 'Windows System.Speech' and heard.get('locale') == 'en-US'
                         and type(heard.get('confidence')) in (int, float) and 0 <= heard['confidence'] <= 1)
                check(f"synthetic_{case['number']}_real_recognition_and_review", valid)
                if valid:
                    expected, observed = words(case['expected']), words(heard['text'])
                    metric = {'id': case['number'], 'audio_bytes': len(raw),
                              'audio_sha256': hashlib.sha256(raw).hexdigest(), 'seconds': elapsed,
                              'reference_words': len(expected), 'word_edits': distance(expected, observed),
                              'exact_normalized': expected == observed, 'confidence': heard['confidence']}
                    metrics.append(metric)
                    raw_rows.append({'id': case['number'], 'expected': case['expected'], 'response': heard})
                check(f"synthetic_{case['number']}_replay_rejected", client.post('/api/speech/transcribe', json=request_body).status_code == 409)

            # Observe actual owned workers before cancelling; no recognition or
            # process-launch mocks are used, and the harness never kills a child.
            inspector = WindowsBackend()
            before_processes = owned_speech_processes(inspector)
            running_id = str(uuid.uuid4())
            with httpx.Client(base_url=origin, timeout=35, trust_env=False,
                              cookies=client.cookies, headers=dict(client.headers)) as parallel:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    pending = executor.submit(parallel.post, '/api/speech/transcribe',
                                              json=body(samples[0][1], request_id=running_id))
                    observed = wait_speech_process(inspector, before_processes)
                    cancelled = client.post('/api/speech/cancel', json={'requestId': running_id})
                    finished = pending.result(timeout=5)
                check('cancel_running_real_worker_and_drain', bool(observed) and cancelled.status_code == 200
                      and finished.status_code == 409 and wait_process_exit(inspector, observed))
            check('cancellation_keeps_session_consent', client.get('/api/speech').json()['micEnabled'])

            # A real TCP disconnect must cancel that worker even if the browser
            # cannot deliver an explicit cancellation request.
            disconnect_id = str(uuid.uuid4())
            upload = json.dumps(body(samples[0][1], request_id=disconnect_id)).encode('ascii')
            cookie = client.build_request('POST', '/api/speech/transcribe').headers['cookie']
            headers = (f'POST /api/speech/transcribe HTTP/1.1\r\nHost: 127.0.0.1:{config.port}\r\n'
                       f'Origin: {origin}\r\nCookie: {cookie}\r\nx-sight-csrf: {client.headers["x-sight-csrf"]}\r\n'
                       f'Content-Type: application/json\r\nContent-Length: {len(upload)}\r\nConnection: close\r\n\r\n')
            before_processes = owned_speech_processes(inspector)
            with socket.create_connection(('127.0.0.1', config.port), timeout=5) as connection:
                connection.sendall(headers.encode('ascii') + upload)
                disconnected_worker = wait_speech_process(inspector, before_processes)
                connection.shutdown(socket.SHUT_RDWR)
            drained = wait_process_exit(inspector, disconnected_worker)
            check('tcp_disconnect_cancels_real_worker', bool(disconnected_worker) and drained)
            check('disconnected_upload_cannot_replay', client.post('/api/speech/transcribe',
                  json=body(samples[0][1], request_id=disconnect_id)).status_code == 409)
            recovery = client.post('/api/speech/transcribe', json=body(samples[0][1]))
            check('new_dictation_works_after_cancellation_and_disconnect', recovery.status_code == 200)
            if recovery.status_code == 200:
                raw_rows.append({'id': 'recovery', 'response': recovery.json()})
            history = client.get('/api/bel/history').json()
            check('transcripts_not_added_to_conversation', not history['items'])
            with sqlite3.connect(data / 'sight.sqlite3') as db:
                counts = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                          for table in ('requests', 'bel_executions', 'bel_history', 'bel_undo')}
            check('transcription_did_not_run_model_or_tools', not any(counts.values()), row_counts=counts)
            revocation = client.post('/api/speech/consent', json={'enabled': False})
            check('revocation_updates_status', revocation.status_code == 200 and not client.get('/api/speech').json()['micEnabled'])
            check('revoked_consent_rejects_audio', client.post('/api/speech/transcribe', json=body(samples[0][1])).status_code == 403)
    except Exception as exc:
        # Do not expose launch/session tokens from HTTP response exception strings.
        check('harness_completed', False, error_type=type(exc).__name__)
    finally:
        host.stop()
        check('backend_shutdown', host.thread is None or not host.thread.is_alive())

    retained_audio = [path for path in data.rglob('*') if path.is_file() and path.suffix.lower() in {'.wav', '.pcm', '.mp3', '.webm'}]
    private_strings = [row['response']['text'].encode('utf-8') for row in raw_rows]
    retained_transcripts = any(needle in path.read_bytes() for path in data.rglob('*') if path.is_file()
                               for needle in private_strings)
    check('no_audio_or_transcript_persisted_by_backend', not retained_audio and not retained_transcripts)
    check('audited_source_unchanged_during_run', all(hashlib.sha256((ROOT / 'sight_core' / name).read_bytes()).hexdigest() == expected
                                                  for name, expected in result['source_sha256'].items()))
    (cache / 'raw-transcripts.json').write_text(json.dumps(raw_rows, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    result.update({'completed_utc': datetime.now(timezone.utc).isoformat(),
                   'elapsed_seconds': round(time.monotonic() - started, 3),
                   'passed': sum(row['passed'] for row in rows), 'total': len(rows),
                   'quality': {'exact_matches': sum(row['exact_normalized'] for row in metrics),
                               'samples': len(metrics), 'reference_words': sum(row['reference_words'] for row in metrics),
                               'word_edits': sum(row['word_edits'] for row in metrics)}})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixtures', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Choose a new evidence path; existing results are immutable')
    result = verify(args.fixtures.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps({'passed': result['passed'], 'total': result['total'], 'quality': result['quality'],
                      'elapsed_seconds': result['elapsed_seconds'], 'evidence': str(args.output.resolve())}))
    return 0 if result['passed'] == result['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
