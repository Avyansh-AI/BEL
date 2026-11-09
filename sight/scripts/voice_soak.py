"""Isolated wall-clock voice lifecycle soak. Never opens a recording device.

Only synthetic or clearly licensed prerecorded PCM fixtures are accepted. Raw
audio and recognition text are never written to evidence. A source backend or
the supplied frozen BEL process serves real authenticated requests.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
from importlib.metadata import distributions
import io
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import uuid
import wave

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source_hashes():
    paths = list((ROOT / 'sight_core').glob('*.py'))
    paths += [p for p in (ROOT.parent / 'frontend/dist').rglob('*') if p.is_file()]
    paths += list(ROOT.glob('requirements*.lock'))
    paths += [Path(__file__), ROOT / 'pyproject.toml']
    return {p.relative_to(ROOT.parent).as_posix(): digest(p) for p in sorted(paths)}


def artifact_hashes(directory):
    if directory is None:
        return {}
    directory = Path(directory).resolve(strict=True)
    return {p.relative_to(directory).as_posix(): digest(p) for p in sorted(directory.rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts}


def load_fixtures(manifest_path):
    """Reject unknown provenance, changed fixtures and paths escaping the corpus."""
    from sight_core.local_speech import validate_audio
    from sight_core.security import safe_file
    manifest_path = safe_file(Path(manifest_path)).resolve(strict=True)
    if manifest_path.stat().st_size > 2_000_000:
        raise ValueError('Corpus manifest exceeds its bound')
    document = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    provenance = document.get('provenance', document.get('source'))
    if (document.get('format') != 1 or document.get('kind') not in {'synthetic', 'recorded_licensed', 'Recorded human read speech'}
            or not isinstance(document.get('license'), str) or not document['license'].strip()
            or not isinstance(provenance, str) or not provenance.strip()):
        raise ValueError('An explicit synthetic or licensed corpus manifest is required')
    files = document.get('files', document.get('clips'))
    if not isinstance(files, list) or not 1 <= len(files) <= 1000:
        raise ValueError('Expected 1..1000 explicitly selected recordings')
    rows = []
    for row in files:
        name = Path(row['path'])
        path = safe_file(manifest_path.parent / name).resolve(strict=True)
        if name.is_absolute() or not path.is_relative_to(manifest_path.parent) or path.suffix.lower() != '.wav':
            raise ValueError('Corpus audio must stay within its manifest directory')
        if path.stat().st_size > 700000:
            raise ValueError('Corpus audio exceeds the speech input bound')
        raw = path.read_bytes()
        expected = row.get('sha256', row.get('wav_sha256'))
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Corpus integrity mismatch')
        validate_audio(raw)
        locale = row.get('locale', 'en-US')
        if locale not in {'en-US', 'en-GB', 'en-IN', 'hi-IN', 'auto'}:
            raise ValueError('Unsupported fixture language')
        rows.append({'audio': base64.b64encode(raw).decode('ascii'), 'sha256': expected, 'locale': locale})
    metadata = {key: document[key] for key in ('format', 'kind', 'license')}
    metadata['provenance'] = provenance
    metadata['manifest_sha256'] = digest(manifest_path)
    metadata['files'] = [{'sha256': row['sha256'], 'locale': row['locale']} for row in rows]
    return rows, metadata


def silent_wav():
    target = io.BytesIO()
    with wave.open(target, 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\0' * 32000)
    return base64.b64encode(target.getvalue()).decode('ascii')


def free_port():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        return listener.getsockname()[1]


class ProcessSampler:
    """Read-only process-tree telemetry: identities and sizes, never window text."""
    def __init__(self, root_pid):
        from sight_core.windows_apps import WindowsBackend
        self.inspector = WindowsBackend()
        self.root_pid = root_pid
        self.psapi = ctypes.WinDLL('psapi', use_last_error=True)
        self.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        self.seen = {}
        self.baseline = set()
        root = self.memory(root_pid)
        if root is None:
            raise OSError('Owned backend process is unavailable')
        self.root_created = root['created']

    def establish_baseline(self):
        """Freeze persistent Python redirectors after readiness, before requests."""
        baseline = set()
        for pid, name in self.processes().items():
            if pid != self.root_pid and name not in {'python.exe', 'pythonw.exe', 'msedgewebview2.exe', 'conhost.exe'}:
                raise OSError('Unexpected child present before recognition')
            row = self.memory(pid, remember=True)
            if row is None:
                raise OSError('Could not identify a persistent backend process')
            if name != 'msedgewebview2.exe':
                baseline.add((pid, row['created']))
        if not baseline:
            raise OSError('Backend baseline is empty')
        self.baseline = baseline

    def processes(self):
        root = self.memory(self.root_pid)
        if root is None or root['created'] != self.root_created:
            return {}
        i = self.inspector
        snapshot = i.kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError('Process snapshot unavailable')
        result = {}
        try:
            entry = i.entry_type()
            entry.dwSize = ctypes.sizeof(entry)
            if not i.kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
                raise OSError('Process enumeration unavailable')
            while True:
                result[int(entry.th32ProcessID)] = (int(entry.th32ParentProcessID), entry.szExeFile.lower())
                if not i.kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                    if ctypes.get_last_error() != 18:
                        raise OSError('Process enumeration incomplete')
                    break
        finally:
            i.kernel.CloseHandle(snapshot)
        owned = {self.root_pid}
        while True:
            descendants = {pid for pid, (parent, _) in result.items() if parent in owned}
            new = descendants - owned
            if not new:
                break
            owned.update(new)
        return {pid: result[pid][1] for pid in owned if pid in result}

    def memory(self, pid, remember=False):
        class Counters(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('faults', wintypes.DWORD)] + [
                (key, ctypes.c_size_t) for key in ('peak_ws', 'working_set', 'peak_paged', 'paged',
                                                  'peak_nonpaged', 'nonpaged', 'pagefile', 'peak_pagefile', 'private')]
        kernel = self.inspector.kernel
        handle = kernel.OpenProcess(0x100410, False, pid)
        if not handle:
            return None
        try:
            kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            if kernel.WaitForSingleObject(handle, 0) != 258:  # WAIT_TIMEOUT: still running
                return None
            times = [ctypes.c_uint64() for _ in range(4)]
            kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(ctypes.c_uint64)] * 4
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                return None
            values = Counters()
            values.cb = ctypes.sizeof(values)
            if not self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(values), values.cb):
                return None
            if remember:
                self.seen[(pid, times[0].value)] = True
            return {'pid': pid, 'created': times[0].value,
                    'working_set_mib': round(values.working_set / 2**20, 3),
                    'private_mib': round(values.private / 2**20, 3),
                    'peak_working_set_mib': round(values.peak_ws / 2**20, 3)}
        finally:
            kernel.CloseHandle(handle)

    def sample(self):
        processes = self.processes()
        rows = []
        for pid, name in processes.items():
            row = self.memory(pid, remember=True)
            if row:
                rows.append({**row, 'name': name})
        # WebView2 has expected persistent subprocesses. Everything else below
        # BEL must drain after a recognition request finishes.
        workers = [row['pid'] for row in rows if row['pid'] != self.root_pid
                   and (row['pid'], row['created']) not in self.baseline and row['name'] != 'msedgewebview2.exe']
        backend = [row for row in rows if row['pid'] == self.root_pid or (row['pid'], row['created']) in self.baseline]
        return {'backend_private_mib': round(sum(row['private_mib'] for row in backend), 3) if backend else None,
                'backend_working_set_mib': round(sum(row['working_set_mib'] for row in backend), 3) if backend else None,
                'tree_working_set_mib': round(sum(row['working_set_mib'] for row in rows), 3),
                'tree_private_mib': round(sum(row['private_mib'] for row in rows), 3),
                'worker_count': len(workers), 'worker_pids': workers,
                'processes': rows}

    def previously_seen_alive(self):
        # PID reuse is not a leak: compare process creation identity as well.
        alive = []
        for pid, created in list(self.seen):
            row = self.memory(pid)
            if row and row['created'] == created:
                alive.append(pid)
        return alive

    def terminate_seen(self):
        """Emergency cleanup only: exact observed process identity, never a name."""
        kernel = self.inspector.kernel
        kernel.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateProcess.restype = wintypes.BOOL
        for pid, created in list(self.seen):
            handle = kernel.OpenProcess(0x101001, False, pid)  # QUERY_LIMITED_INFORMATION | TERMINATE | SYNCHRONIZE
            if not handle:
                continue
            try:
                times = [ctypes.c_uint64() for _ in range(4)]
                if (kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times))
                        and times[0].value == created):
                    kernel.TerminateProcess(handle, 1)
                    kernel.WaitForSingleObject(handle, 5000)
            finally:
                kernel.CloseHandle(handle)


def host_memory():
    class Memory(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
            (key, ctypes.c_uint64) for key in ('total', 'available', 'page_total', 'page_available',
                                            'virtual_total', 'virtual_available', 'extended')]
    value = Memory()
    value.length = ctypes.sizeof(value)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(value)):
        return {}
    return {'host_available_mib': round(value.available / 2**20, 3),
            'host_commit_available_mib': round(value.page_available / 2**20, 3)}


def memory_summary(rows, duration):
    eligible = [row for row in rows if row.get('quiescent') and
                type(row.get('backend_private_mib')) in (float, int) and
                math.isfinite(row['backend_private_mib'])]
    early = [r['backend_private_mib'] for r in eligible if duration / 6 <= r['elapsed'] < duration / 3]
    late = [r['backend_private_mib'] for r in eligible if r['elapsed'] >= duration * 5 / 6]
    if len(early) < 3 or len(late) < 3:
        return {'status': 'NOT TESTED', 'reason': 'Insufficient quiescent samples after warm-up'}
    baseline, final = statistics.median(early), statistics.median(late)
    growth, allowance = final - baseline, max(64.0, baseline * .25)
    return {'status': 'PASS' if growth <= allowance else 'FAIL',
            'baseline_private_mib': baseline, 'final_private_mib': final,
            'growth_mib': round(growth, 3), 'provisional_allowance_mib': round(allowance, 3),
            'definition': 'Quiescent median minutes 10–20 versus 50–60 for an hour; tolerance max(64 MiB,25%).'}


class Telemetry:
    def __init__(self, sampler, private_path, start):
        self.sampler, self.path, self.start = sampler, private_path, start
        self.stop = threading.Event()
        self.rows = []
        self.quiescent = False
        self.thread = threading.Thread(target=self.run, name='BEL-voice-soak-telemetry', daemon=True)

    def run(self):
        next_gpu = 0.0
        gpu = {}
        with self.path.open('x', encoding='utf-8') as output:
            while not self.stop.is_set():
                elapsed = time.monotonic() - self.start
                try:
                    row = self.sampler.sample() | host_memory()
                except OSError:
                    row = {'telemetry_error': 'process_or_memory_unavailable'}
                if elapsed >= next_gpu:
                    next_gpu = elapsed + 15
                    try:
                        result = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu,temperature.gpu',
                                                 '--format=csv,noheader,nounits'], capture_output=True,
                                                text=True, timeout=5, creationflags=0x08000000, check=True)
                        used, busy, temperature = [float(v.strip()) for v in result.stdout.splitlines()[0].split(',')]
                        gpu = {'board_gpu_used_mib': used, 'board_gpu_utilization_percent': busy, 'board_gpu_temperature_c': temperature}
                    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                        gpu = {'gpu_measurement': 'NOT TESTED'}
                row.update(gpu, elapsed=round(elapsed, 3), quiescent=self.quiescent)
                self.rows.append(row)
                output.write(json.dumps(row) + '\n')
                output.flush()
                self.stop.wait(1)


async def serve():
    import uvicorn
    from sight_core.api import create_app
    from sight_core.config import Config
    from sight_core.cli import single_instance
    config = Config.from_env()
    with single_instance(config.data_dir):
        server = uvicorn.Server(uvicorn.Config(create_app(config, local_only=True), host='127.0.0.1',
                                port=config.port, access_log=False, server_header=False))
        async def watch():
            while not server.should_exit:
                if (config.data_dir / 'voice-soak-stop').exists():
                    server.should_exit = True
                    break
                await asyncio.sleep(.1)
        watcher = asyncio.create_task(watch())
        try:
            await server.serve()
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)


def run(args):
    if os.name != 'nt':
        raise ValueError('Actual Windows execution is required')
    if not 10 <= args.seconds <= 7200:
        raise ValueError('Use 10..7200 seconds; only at least 3600 can qualify the hour gate')
    fixtures, provenance = load_fixtures(args.corpus)
    if args.output.exists():
        raise ValueError('Evidence already exists; choose a new output')
    identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    cache = ROOT.parent / '.cache' / ('voice-soak-' + identifier)
    cache.mkdir(parents=True)
    data = cache / 'data'
    port, debug_port = free_port(), free_port()
    while port == debug_port:
        debug_port = free_port()
    origin = f'http://127.0.0.1:{port}'
    before_sources = source_hashes()
    before_assets = artifact_hashes(args.asr_directory)
    before_frozen = artifact_hashes(args.executable.parent) if args.executable else {}
    versions = dict(sorted((d.metadata['Name'], d.version) for d in distributions()))
    result = {'format': 1, 'kind': 'Actual Windows voice lifecycle stability; prerecorded input only',
              'requested_seconds': args.seconds, 'engine': args.engine, 'model': args.asr_model,
              'started_utc': datetime.now(timezone.utc).isoformat(), 'source_sha256': before_sources,
              'asr_sha256': before_assets, 'frozen_sha256': before_frozen, 'dependencies': versions,
              'corpus': provenance, 'physical_microphone_access': False, 'cloud_inference_requests': 0,
              'audible_playback': False, 'checks': [], 'cycles': 0, 'recognition_latencies': [],
              'complete': False, 'one_hour_qualified': False,
              'limitations': ['No physical microphone, hardware permissions, acoustic echo protection or wake activation tested.',
                              'GPU values describe the shared board, not exclusively the ASR process.',
                              'Memory peaks are sampled; OS process peak working set is also captured when a process is observed.']}
    started = time.monotonic()
    process = client = other = telemetry = browser = playwright = page = None
    sampler = None
    lifecycle_started = None
    lifecycle_elapsed = 0.0

    def save():
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        (cache / 'progress.json').write_text(json.dumps(result, indent=2), encoding='utf-8')

    def check(name, passed, **details):
        result['checks'].append({'id': name, 'passed': bool(passed), 'elapsed': round(time.monotonic() - started, 3), **details})
        if not passed:
            save()
            raise AssertionError(name)

    def body(row, request_id=None):
        return {'audio': row['audio'], 'mimeType': 'audio/wav', 'locale': row['locale'],
                'engine': args.engine, 'allow_fallback': False, 'requestId': request_id or str(uuid.uuid4())}

    def authenticate(connection):
        token = (data / 'browser-token').read_text()
        connection.post('/api/session/claim', json={'token': token}, headers={'origin': origin}).raise_for_status()
        connection.headers['x-sight-csrf'] = connection.get('/api/session').json()['csrf']

    def workers_drained(sampler, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if sampler.sample()['worker_count'] == 0:
                return True
            time.sleep(.05)
        return False

    try:
        env = dict(os.environ)
        for key in list(env):
            if key.startswith(('BEL_', 'SIGHT_', 'WEBVIEW2_')):
                env.pop(key)
        env.update(BEL_DATA_DIR=str(data), BEL_PORT=str(port), BEL_OLLAMA_MODEL='',
                   BEL_LOCAL_STT='windows', BEL_SPEECH_ENGINE=args.engine, BEL_ASR_MODEL=args.asr_model)
        if args.asr_directory:
            env['BEL_ASR_DIRECTORY'] = str(args.asr_directory.resolve(strict=True))
        if args.executable:
            executable = args.executable.resolve(strict=True)
            env['WEBVIEW2_USER_DATA_FOLDER'] = str(cache / 'webview-profile')
            env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'] = (
                f'--remote-debugging-address=127.0.0.1 --remote-debugging-port={debug_port} '
                '--mute-audio --use-fake-device-for-media-stream')
            command = [str(executable), '--background', '--local-dictation', '--data-directory', str(data), '--port', str(port)]
        else:
            command = [sys.executable, '-B', str(Path(__file__)), '--_server']
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
        sampler = ProcessSampler(process.pid)
        telemetry = Telemetry(sampler, cache / 'telemetry.jsonl', started)
        telemetry.thread.start()
        client = httpx.Client(base_url=origin, trust_env=False, timeout=120)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and process.poll() is None:
            try:
                if client.get('/api/session', timeout=1).status_code == 401:
                    authenticate(client)
                    break
            except (httpx.HTTPError, OSError):
                pass
            time.sleep(.1)
        check('backend_ready', process.poll() is None and client.get('/api/health').status_code == 200)
        other = httpx.Client(base_url=origin, trust_env=False, timeout=120)
        authenticate(other)
        check('consent_initially_off', not client.get('/api/speech').json()['micEnabled'])
        sampler.establish_baseline()
        if args.executable:
            from acceptance_speech_native import loopback_listeners
            from playwright.sync_api import sync_playwright
            deadline = time.monotonic() + 30
            with httpx.Client(trust_env=False, timeout=1) as debug:
                while True:
                    try:
                        if debug.get(f'http://127.0.0.1:{debug_port}/json/version').status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if time.monotonic() >= deadline:
                        raise TimeoutError('Owned native renderer unavailable')
                    time.sleep(.1)
            listeners = loopback_listeners(debug_port)
            check('debug_listener_loopback_only', bool(listeners) and set(listeners) <= {'127.0.0.1', '::1'})
            playwright = sync_playwright().start()
            browser = playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{debug_port}')
            pages = [p for context in browser.contexts for p in context.pages if p.url.startswith(origin + '/')]
            check('exact_owned_native_page', len(pages) == 1)
            page = pages[0]
            page.wait_for_function('!!window.pywebview?.api?.close_app')
            page.evaluate("() => { navigator.mediaDevices.getUserMedia=()=>Promise.reject(new Error('No physical capture in stability test')); }")
        cycle = 0
        lifecycle_started = time.monotonic()
        result['lifecycle_started_utc'] = datetime.now(timezone.utc).isoformat()
        result['startup_seconds'] = round(lifecycle_started - started, 3)
        # Startup, asset verification and shutdown never count toward an hour.
        while time.monotonic() - lifecycle_started < args.seconds:
            cycle_start = time.monotonic()
            telemetry.quiescent = False
            check('source_still_frozen', source_hashes() == before_sources)
            check('backend_alive', process.poll() is None)
            health = client.get('/api/health').json()
            check('health_local_only', health['ok'] and not health['cloud_enabled'])
            selected = fixtures[cycle % len(fixtures)]
            check('second_session_cannot_recognize', other.post('/api/speech/transcribe', json=body(selected)).status_code == 403)
            check('explicit_consent_granted', client.post('/api/speech/consent', json={'enabled': True}).json() == {'enabled': True})
            payload = body(selected)
            tick = time.monotonic()
            response = client.post('/api/speech/transcribe', json=payload)
            result['recognition_latencies'].append(round(time.monotonic() - tick, 3))
            value = response.json()
            text = value.get('text')
            check('real_recognition_review_only', response.status_code == 200 and isinstance(text, str) and bool(text.strip())
                  and value.get('review_required') is True
                  and (value.get('engine_id') == args.engine or
                       (args.engine == 'windows' and value.get('engine') == 'Windows System.Speech')))
            del text, value
            check('replay_rejected', client.post('/api/speech/transcribe', json=payload).status_code == 409)
            cancelled_id = str(uuid.uuid4())
            check('cancel_before_upload', client.post('/api/speech/cancel', json={'requestId': cancelled_id}).status_code == 200
                  and client.post('/api/speech/transcribe', json=body(selected, cancelled_id)).status_code == 409)
            if cycle % 5 == 0:
                quiet = body(selected)
                quiet['audio'] = silent_wav()
                check('silence_rejected_without_draft', client.post('/api/speech/transcribe', json=quiet).status_code == 422)
            running = str(uuid.uuid4())
            with httpx.Client(base_url=origin, trust_env=False, timeout=120, cookies=client.cookies,
                              headers=dict(client.headers)) as parallel, ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(parallel.post, '/api/speech/transcribe', json=body(selected, running))
                deadline = time.monotonic() + 15
                observed = False
                while time.monotonic() < deadline and not future.done():
                    if sampler.sample()['worker_count']:
                        observed = True
                        break
                    time.sleep(.01)
                stop = client.post('/api/speech/cancel', json={'requestId': running})
                finished = future.result(timeout=30)
                check('running_worker_cancelled', observed and stop.status_code == 200 and finished.status_code == 409)
            check('workers_drained_after_cancel', workers_drained(sampler))
            check('consent_revoked', client.post('/api/speech/consent', json={'enabled': False}).json() == {'enabled': False})
            check('revocation_blocks_input', client.post('/api/speech/transcribe', json=body(selected)).status_code == 403)
            check('no_speech_history', not client.get('/api/bel/history').json()['items'])
            if page and cycle % 10 == 0:
                for mode in ('active', 'compact', 'background'):
                    check('native_mode_' + mode, page.evaluate('(mode)=>window.pywebview.api.set_mode(mode)', mode)['mode'] == mode)
            result['cycles'] = cycle + 1
            cycle += 1
            telemetry.quiescent = True
            save()
            while time.monotonic() - cycle_start < 60 and time.monotonic() - lifecycle_started < args.seconds:
                if process.poll() is not None:
                    raise RuntimeError('Backend exited unexpectedly')
                time.sleep(min(1, max(.01, args.seconds - (time.monotonic() - lifecycle_started))))
        lifecycle_elapsed = time.monotonic() - lifecycle_started
        check('final_workers_drained', workers_drained(sampler))
        if page:
            page.evaluate('setTimeout(()=>window.pywebview.api.close_app(),100)')
        else:
            (data / 'voice-soak-stop').write_text('stop', encoding='ascii')
        check('clean_process_exit', process.wait(timeout=30) == 0)
        deadline = time.monotonic() + 10
        while sampler.previously_seen_alive() and time.monotonic() < deadline:
            time.sleep(.1)
        check('no_surviving_owned_processes', not sampler.previously_seen_alive())
        telemetry.stop.set()
        telemetry.thread.join(10)
        check('telemetry_stopped', not telemetry.thread.is_alive())
        # Inspect only synthetic/approved test state, never the owner's data.
        with sqlite3.connect(data / 'sight.sqlite3') as db:
            counts = {name: db.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                      for name in ('requests', 'bel_history', 'bel_executions', 'bel_undo')}
        check('no_message_or_tool_side_effects', not any(counts.values()), counts=counts)
        check('no_audio_retained', not any(p.is_file() and p.suffix.lower() in {'.wav', '.pcm', '.webm', '.mp3'} for p in data.rglob('*')))
        check('source_unchanged', source_hashes() == before_sources)
        check('asr_assets_unchanged', artifact_hashes(args.asr_directory) == before_assets)
        check('frozen_files_unchanged', (artifact_hashes(args.executable.parent) if args.executable else {}) == before_frozen)
        check('dependencies_unchanged', dict(sorted((d.metadata['Name'], d.version) for d in distributions())) == versions)
        result['complete'] = True
    except Exception as exc:
        # HTTP errors can include session URLs. Publish only an exception class.
        result['error_type'] = type(exc).__name__
    finally:
        if lifecycle_started is not None and not lifecycle_elapsed:
            lifecycle_elapsed = time.monotonic() - lifecycle_started
        if client:
            client.close()
        if other:
            other.close()
        if process is not None and process.poll() is None:
            if sampler:
                # Discover live children before root termination destroys the
                # observed process tree; exact creation times prevent PID reuse.
                try:
                    sampler.sample()
                except OSError:
                    pass
            process.kill()
            process.wait(timeout=10)
            result['forced_cleanup'] = True
        if telemetry:
            telemetry.stop.set()
            telemetry.thread.join(10)
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if playwright:
            playwright.stop()
        if sampler and sampler.previously_seen_alive():
            sampler.terminate_seen()
            result['forced_cleanup'] = True
            deadline = time.monotonic() + 10
            while sampler.previously_seen_alive() and time.monotonic() < deadline:
                time.sleep(.1)
        rows = telemetry.rows if telemetry else []
        startup = result.get('startup_seconds', 0)
        lifecycle_rows = [dict(row, elapsed=row['elapsed'] - startup) for row in rows
                          if startup <= row['elapsed'] <= startup + lifecycle_elapsed]
        ticks = [0.0] + [row['elapsed'] for row in lifecycle_rows] + [lifecycle_elapsed]
        largest_gap = max((right - left for left, right in zip(ticks, ticks[1:])), default=lifecycle_elapsed)
        continuity = (len(lifecycle_rows) >= args.seconds * .8 and largest_gap <= 15
                      and result['cycles'] >= max(1, int(args.seconds / 60 * .9)))
        numeric = lambda key: [row[key] for row in rows if type(row.get(key)) in (int, float)]
        result['telemetry'] = {'samples': len(rows), 'errors': sum('telemetry_error' in row for row in rows),
            'peak_tree_working_set_mib': max(numeric('tree_working_set_mib'), default=None),
            'peak_tree_private_mib': max(numeric('tree_private_mib'), default=None),
            'minimum_host_available_mib': min(numeric('host_available_mib'), default=None),
            'peak_board_gpu_used_mib': max(numeric('board_gpu_used_mib'), default=None),
            'peak_observed_worker_count': max(numeric('worker_count'), default=None),
            'quiescent_memory': memory_summary(lifecycle_rows, args.seconds)}
        result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        result['lifecycle_seconds'] = round(lifecycle_elapsed, 3)
        result['continuity'] = {'passed': continuity, 'lifecycle_samples': len(lifecycle_rows),
                                'largest_sample_gap_seconds': round(largest_gap, 3),
                                'minimum_cycles': max(1, int(args.seconds / 60 * .9)),
                                'rule': 'At least 0.8 samples/second, no sample gap over 15s, at least 90% of planned minute cycles. Suspended or stalled runs cannot pass the hour gate.'}
        result['surviving_owned_processes'] = sampler.previously_seen_alive() if sampler else []
        with socket.socket() as probe:
            result['backend_listener_closed'] = probe.connect_ex(('127.0.0.1', port)) != 0
        result['passed'] = sum(row['passed'] for row in result['checks'])
        result['total'] = len(result['checks'])
        result['one_hour_qualified'] = (result['complete'] and args.seconds >= 3600 and lifecycle_elapsed >= args.seconds
                                       and result['passed'] == result['total'] and result['backend_listener_closed']
                                       and result['telemetry']['quiescent_memory']['status'] == 'PASS'
                                       and result['telemetry']['errors'] == 0 and not result.get('forced_cleanup')
                                       and continuity
                                       and not result['surviving_owned_processes'])
        result['status'] = 'PASS' if result['one_hour_qualified'] else 'PARTIAL' if result['complete'] else 'FAIL'
        result['completed_utc'] = datetime.now(timezone.utc).isoformat()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as output:
            json.dump(result, output, indent=2)
            output.write('\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--_server', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--seconds', type=int, default=3600)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--engine', choices=['windows', 'whisper_cpp'], default='whisper_cpp')
    parser.add_argument('--asr-directory', type=Path)
    parser.add_argument('--asr-model', choices=['base-q5_1', 'small-q5_1'], default='small-q5_1')
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args._server:
        asyncio.run(serve())
        return 0
    if args.corpus is None or args.output is None:
        parser.error('--corpus and --output are required')
    result = run(args)
    print(json.dumps({key: result[key] for key in ('status', 'passed', 'total', 'elapsed_seconds', 'one_hour_qualified')}))
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
