"""Exercise an actual BEL release in an isolated, synthetic owner directory.

Only BEL windows, its loopback server and bundled fixed workers are exercised.
No microphone, owner applications, cloud requests or auto-start changes occur.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

import httpx


def run_worker(executable, kind, payload, *arguments):
    started = time.monotonic()
    result = subprocess.run([str(executable), '--worker', kind, *arguments],
                            input=json.dumps(payload).encode(), capture_output=True,
                            timeout=30, creationflags=0x08000000)
    parsed = json.loads(result.stdout)
    return result.returncode, parsed, round(time.monotonic() - started, 4)


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--needle-assets', type=Path)
    args = parser.parse_args()
    if os.name != 'nt':
        raise SystemExit('Windows validation requires Windows')
    exe = args.executable.resolve(strict=True)
    worker = exe.with_name('BEL-worker.exe')
    repo = Path(__file__).resolve().parents[2]
    temporary = repo / '.cache' / ('windows-verify-' + uuid.uuid4().hex)
    temporary.mkdir(parents=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = {'kind': 'actual_windows_release', 'executable_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
              'worker_sha256': hashlib.sha256(worker.read_bytes()).hexdigest(), 'checks': {}, 'timings': {},
              'native': [], 'limitations': ['Installed WebView2 and Chromium reused; this is not a fresh Windows account test.',
                                             'No microphone capture, owner wake model or cloud inference exercised.']}
    checks = result['checks']
    started = time.monotonic()
    try:
        code, data, elapsed = run_worker(worker, 'skill', {'text': '  hello  ', 'operations': [{'op': 'trim'}, {'op': 'upper'}]})
        checks['declarative_worker'] = code == 0 and data == {'ok': True, 'result': 'HELLO'}
        result['timings']['skill_worker_seconds'] = elapsed
        code, data, _ = run_worker(worker, 'skill', {'text': 'hi', 'operations': [{'op': 'exec', 'value': 'untrusted'}]})
        checks['executable_operation_rejected'] = code != 0 and data.get('ok') is False
        code, data, elapsed = run_worker(worker, 'capability', {'id': 'speech.render', 'arguments': {'text': 'BEL desktop verification.'}})
        wav = base64.b64decode(data.get('wav', ''), validate=True)
        checks['local_sapi_wav'] = code == 0 and wav[:4] == b'RIFF' and wav[8:12] == b'WAVE' and len(wav) > 1000
        result['timings']['speech_worker_seconds'] = elapsed
        code, data, elapsed = run_worker(worker, 'capability', {'id': 'browser.inspect', 'arguments': {'html': '<!doctype html><title>BEL test</title><h1>Local release verification</h1>', 'fields': {}}})
        png = base64.b64decode(data.get('screenshot', ''), validate=True)
        checks['offline_chromium_capture'] = code == 0 and png[:8] == b'\x89PNG\r\n\x1a\n' and len(png) > 1000
        result['timings']['browser_worker_seconds'] = elapsed
        if args.needle_assets:
            code, data, elapsed = run_worker(worker, 'needle', {'text': 'Open Notepad', 'max_new_tokens': 256,
                'tools': [{'name': 'app.launch', 'description': 'Open Notepad or Calculator', 'parameters': {
                    'type': 'object', 'properties': {'application': {'type': 'string', 'enum': ['notepad', 'calculator']}},
                    'required': ['application'], 'additionalProperties': False}}]}, '--assets', str(args.needle_assets.resolve()))
            checks['native_needle_worker'] = code == 0 and data.get('ok') is True
            result['timings']['needle_worker_seconds'] = elapsed
        directory = temporary / 'data'
        port = free_port()
        for attempt in (1, 2):
            report = temporary / f'native-{attempt}.json'
            env = dict(os.environ)
            for key in ('BEL_DATA_DIR', 'SIGHT_DATA_DIR', 'BEL_OLLAMA_MODEL', 'SIGHT_OLLAMA_MODEL', 'BEL_PORT', 'SIGHT_PORT'):
                env.pop(key, None)
            launch_started = time.monotonic()
            process = subprocess.Popen([str(exe), '--data-directory', str(directory), '--port', str(port), '--smoke-test', str(report)],
                env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
            # Read/write synthetic preferences through the same authenticated API.
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=3) as client:
                deadline = time.monotonic() + 35
                connected = False
                while time.monotonic() < deadline and process.poll() is None:
                    try:
                        token = (directory / 'browser-token').read_text()
                        claim = client.post('/api/session/claim', json={'token': token}, headers={'origin': f'http://127.0.0.1:{port}'})
                        if claim.status_code == 200:
                            client.headers['x-sight-csrf'] = client.get('/api/session').json()['csrf']
                            connected = True
                            break
                    except (OSError, httpx.HTTPError, KeyError, ValueError):
                        pass
                    time.sleep(.1)
                checks[f'authenticated_http_{attempt}'] = connected
                if connected:
                    if attempt == 1:
                        saved = client.post('/api/settings', json={'textOnly': True, 'notifications': True, 'startupBriefing': False})
                        checks['settings_saved'] = saved.status_code == 200
                    else:
                        checks['settings_survive_restart'] = client.get('/api/settings').json()['preferences']['notifications'] is True
            try:
                code = process.wait(timeout=65)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                code = -1
            checks[f'clean_exit_{attempt}'] = code == 0
            result['timings'][f'desktop_process_seconds_{attempt}'] = round(time.monotonic() - launch_started, 3)
            if report.is_file():
                native = json.loads(report.read_text())
                result['native'].append(native)
                checks[f'native_lifecycle_{attempt}'] = native.get('status') == 'PASS'
            else:
                checks[f'native_lifecycle_{attempt}'] = False
            with socket.socket() as probe:
                checks[f'backend_stopped_{attempt}'] = probe.connect_ex(('127.0.0.1', port)) != 0
            checks['writable_log_directory'] = (directory / 'desktop.log').is_file()
    except Exception as exc:
        result['error_type'] = type(exc).__name__
        checks['harness_completed'] = False
    else:
        checks['harness_completed'] = True
    result['elapsed_seconds'] = round(time.monotonic() - started, 3)
    result['status'] = 'PASS' if all(checks.values()) else 'FAIL'
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({'status': result['status'], 'passed': sum(checks.values()), 'checks': len(checks), 'output': str(args.output)}))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
