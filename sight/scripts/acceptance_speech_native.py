"""Verify frozen BEL dictation with synthetic WAV input and its own native window.

Only this disposable test process receives a loopback WebView2 debugging port.
The native bridge handles presentation and clean exit; actual speech travels
through the authenticated API. No physical audio capture or playback occurs.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import uuid

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sight_core.local_speech import powershell_path
from verify_frozen_source import verify


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def loopback_listeners(port):
    # A validated integer is the only variable in this read-only fixed command.
    command = (f'@(Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction Stop | '
               'ForEach-Object { $_.LocalAddress }) | ConvertTo-Json -Compress')
    query = subprocess.run([str(powershell_path()), '-NoLogo', '-NoProfile', '-NonInteractive', '-Command', command],
                           capture_output=True, timeout=15, creationflags=0x08000000)
    if query.returncode:
        return []
    rows = json.loads(query.stdout.decode('utf-8-sig'))
    return rows if isinstance(rows, list) else [rows]


def run(executable, fixture, engine='windows', asr_directory=None):
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    cache = ROOT.parent / '.cache' / ('speech-native-' + run_id)
    data = cache / 'data'
    cache.mkdir(parents=True)
    port, debug_port = free_port(), free_port()
    while debug_port == port:
        debug_port = free_port()
    origin, debug_origin = f'http://127.0.0.1:{port}', f'http://127.0.0.1:{debug_port}'
    env = dict(os.environ)
    for key in ('BEL_DATA_DIR', 'SIGHT_DATA_DIR', 'BEL_PORT', 'SIGHT_PORT', 'BEL_LOCAL_STT', 'SIGHT_LOCAL_STT',
                'BEL_OLLAMA_MODEL', 'SIGHT_OLLAMA_MODEL', 'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', 'WEBVIEW2_USER_DATA_FOLDER'):
        env.pop(key, None)
    env['BEL_OLLAMA_MODEL'] = ''  # No inference is required for this test.
    env['BEL_SPEECH_ENGINE'] = engine
    env['BEL_ASR_MODEL'] = 'small-q5_1'
    if asr_directory is not None:
        env['BEL_ASR_DIRECTORY'] = str(asr_directory.resolve(strict=True))
    env['WEBVIEW2_USER_DATA_FOLDER'] = str(cache / 'webview-profile')
    env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (
        f'--remote-debugging-address=127.0.0.1 --remote-debugging-port={debug_port} '
        '--mute-audio --use-fake-device-for-media-stream')
    raw = fixture.read_bytes()
    audio = base64.b64encode(raw).decode('ascii')
    checks, transcript = [], ''
    started = time.monotonic()
    result = {'format': 1, 'kind': 'Frozen BEL, actual native WebView2 and local speech', 'requested_engine': engine,
              'run_id': run_id, 'started_utc': datetime.now(timezone.utc).isoformat(),
              'executable_sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
              'fixture_sha256': hashlib.sha256(raw).hexdigest(),
              'physical_microphone_access': False, 'audible_playback': False, 'cloud_inference_requests': 0,
              'checks': checks, 'limitations': [
                  'Prerecorded synthetic WAV sent over HTTP; this does not qualify native microphone permissions or human recognition.',
                  'Installed WebView2 and speech runtime reused; fresh Windows account remains untested.',
                  'A loopback-only debug port was enabled solely in this disposable test process; ordinary launches do not set it.',
                  'No BEL wake-word model or Hindi accuracy qualification is supplied by this test.']}

    def check(name, passed, **details):
        checks.append({'id': name, 'passed': bool(passed), **details})

    process = None
    try:
        modules = {name: verify(executable.with_name(name), ROOT) for name in ('BEL.exe', 'BEL-worker.exe')}
        check('frozen_python_matches_current_source', all(modules.values()), matched_modules=modules)
        process = subprocess.Popen([str(executable), '--background', '--local-dictation',
                                    '--data-directory', str(data), '--port', str(port)],
                                   env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, creationflags=0x08000000)
        with httpx.Client(base_url=origin, trust_env=False, timeout=75) as client:
            connected = False
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    token = (data / 'browser-token').read_text()
                    claim = client.post('/api/session/claim', json={'token': token}, headers={'origin': origin})
                    if claim.status_code == 200:
                        client.headers['x-sight-csrf'] = client.get('/api/session').json()['csrf']
                        connected = True
                        break
                except (OSError, ValueError, KeyError, httpx.HTTPError):
                    pass
                time.sleep(.1)
            check('frozen_authenticated_backend_started', connected)
            if not connected:
                raise RuntimeError('Frozen backend did not start')
            result['backend_ready_seconds'] = round(time.monotonic() - started, 3)
            status = client.get('/api/speech').json()
            check('frozen_english_recognizer_available', status['stt']['configured'] and 'en-US' in status['stt']['locales'])
            check('consent_defaults_off_and_wake_unavailable', not status['micEnabled'] and not status['wake']['enabled'])
            make_audio = lambda: {'audio': audio, 'mimeType': 'audio/wav', 'locale': 'en-US',
                                 'engine': engine, 'allow_fallback': False, 'requestId': str(uuid.uuid4())}
            check('frozen_no_consent_rejects_audio', client.post('/api/speech/transcribe', json=make_audio()).status_code == 403)
            check('frozen_explicit_consent', client.post('/api/speech/consent', json={'enabled': True}).json() == {'enabled': True})
            before = time.monotonic()
            recognized = client.post('/api/speech/transcribe', json=make_audio())
            heard = recognized.json()
            result['recognition_seconds'] = round(time.monotonic() - before, 3)
            confidence_valid = (heard.get('confidence') is None and heard.get('confidence_kind') == 'unavailable') if engine == 'whisper_cpp' else (type(heard.get('confidence')) in (int, float) and 0 <= heard['confidence'] <= 1)
            valid = (recognized.status_code == 200 and heard.get('engine_id') == engine
                     and isinstance(heard.get('text'), str) and bool(heard['text'].strip())
                     and heard.get('review_required') is True and heard.get('locale') == 'en-US'
                     and confidence_valid)
            check('frozen_actual_recognition_requires_review', valid)
            if valid:
                transcript = heard['text']
                result['recognition'] = {'characters': len(transcript), 'confidence': heard['confidence']}
            check('frozen_no_transcript_in_history', not client.get('/api/bel/history').json()['items'])
            check('frozen_consent_revoked', client.post('/api/speech/consent', json={'enabled': False}).json() == {'enabled': False})
            check('frozen_revocation_rejects_audio', client.post('/api/speech/transcribe', json=make_audio()).status_code == 403)

            # Attach only to the owned disposable WebView2, never the owner's browser.
            deadline = time.monotonic() + 30
            with httpx.Client(trust_env=False, timeout=1) as debug:
                while True:
                    try:
                        if debug.get(debug_origin + '/json/version').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() >= deadline or process.poll() is not None:
                        raise RuntimeError('Owned native renderer debug endpoint unavailable')
                    time.sleep(.1)
            listeners = loopback_listeners(debug_port)
            safe_debug = bool(listeners) and set(listeners) <= {'127.0.0.1', '::1'}
            check('test_debug_listener_is_loopback_only', safe_debug, addresses=listeners)
            if not safe_debug:
                raise RuntimeError('Debug listener scope unavailable or unsafe')
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(debug_origin, timeout=10000)
                result['webview_version'] = browser.version
                pages = [page for context in browser.contexts for page in context.pages if page.url.startswith(origin + '/')]
                if len(pages) != 1:
                    raise RuntimeError('Expected exactly one own application page')
                page = pages[0]
                page.wait_for_function('!!window.pywebview?.api?.status && !!document.querySelector("#root > *")')
                # Belt-and-braces guard: no microphone request can succeed in this test.
                page.evaluate('''() => { window.__belMicAttempts = 0;
                    navigator.mediaDevices.getUserMedia = () => { window.__belMicAttempts++;
                        return Promise.reject(new Error('Physical microphone prohibited in this test')); }; }''')
                state = page.evaluate('window.pywebview.api.status()')
                check('native_background_and_tray', state['mode'] == 'background' and state['tray_available'])
                check('native_frontend_loaded', page.title().startswith('BEL') and page.locator('#root > *').count() > 0)
                # This renderer has a separate owner session; API consent must not leak into it.
                page.evaluate('window.pywebview.api.set_mode("active")')
                page.get_by_role('button', name='Settings', exact=True).click()
                consent = page.get_by_role('switch', name='Microphone consent', exact=True)
                expect(consent).to_be_enabled()
                check('native_renderer_session_still_muted', consent.get_attribute('aria-checked') == 'false')
                page.get_by_role('button', name='Close panel', exact=True).click()
                compact = page.evaluate('window.pywebview.api.set_mode("compact")')
                check('native_compact', compact['mode'] == 'compact')
                background = page.evaluate('window.pywebview.api.set_mode("background")')
                check('native_background_keeps_backend_alive', background['mode'] == 'background' and client.get('/api/health').status_code == 200)
                active = page.evaluate('window.pywebview.api.set_mode("active")')
                check('native_restore', active['mode'] == 'active')
                check('native_no_microphone_calls', page.evaluate('window.__belMicAttempts') == 0)
                page.evaluate('setTimeout(() => window.pywebview.api.close_app(), 100)')
                code = process.wait(timeout=20)
                check('frozen_clean_exit', code == 0)
                browser.close()
    except Exception as exc:
        check('native_harness_completed', False, error_type=type(exc).__name__)
        (cache / 'failure.txt').write_text(str(exc), encoding='utf-8')
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
            check('forced_cleanup_was_not_required', False)
    with socket.socket() as probe:
        check('frozen_backend_stopped', probe.connect_ex(('127.0.0.1', port)) != 0)
    with socket.socket() as probe:
        check('test_debug_port_stopped', probe.connect_ex(('127.0.0.1', debug_port)) != 0)
    if (data / 'sight.sqlite3').is_file():
        with sqlite3.connect(data / 'sight.sqlite3') as db:
            counts = {table: db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]
                      for table in ('requests', 'bel_executions', 'bel_history')}
        check('frozen_speech_no_model_tool_or_chat_side_effects', not any(counts.values()), row_counts=counts)
        retained_audio = any(p.is_file() and p.suffix.lower() in {'.wav', '.pcm', '.mp3', '.webm'} for p in data.rglob('*'))
        retained_text = bool(transcript) and any(transcript.encode('utf-8') in p.read_bytes() for p in data.rglob('*') if p.is_file())
        check('frozen_speech_does_not_persist_audio_or_transcript', not retained_audio and not retained_text)
    (cache / 'transcript.txt').write_text(transcript, encoding='utf-8')
    result.update(passed=sum(row['passed'] for row in checks), total=len(checks),
                  elapsed_seconds=round(time.monotonic() - started, 3),
                  completed_utc=datetime.now(timezone.utc).isoformat())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', required=True, type=Path)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--engine', choices=('windows', 'whisper_cpp'), default='windows')
    parser.add_argument('--asr-directory', type=Path)
    args = parser.parse_args()
    if os.name != 'nt' or args.output.exists():
        raise SystemExit('Windows and a new evidence path are required')
    result = run(args.executable.resolve(strict=True), args.fixture.resolve(strict=True), args.engine, args.asr_directory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'passed': result['passed'], 'total': result['total'], 'evidence': str(args.output.resolve())}))
    return 0 if result['passed'] == result['total'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
