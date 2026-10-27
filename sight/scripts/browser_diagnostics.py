"""Bounded real-browser reproductions with synthetic input and safe telemetry.

No memory exhaustion, owner page, provider request, or browser-policy changes.
Each attempt runs in a fresh child process; failures are retained, not retried.
"""
import argparse
import base64
import ctypes
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CASES = {
    'original_install': {'html': '<title>Fresh offline install</title><p>Current audit</p>', 'fields': {}},
    'local_fields': {'html': '<title>Field fixture</title><p>Synthetic page</p><input id="name">', 'fields': {'name': 'Synthetic'}},
    'blocked_content': {'html': '<title>Blocked content</title><p>Offline fixture</p><img src="https://example.invalid/image.png"><script>document.title="SCRIPT_RAN"</script>', 'fields': {}},
}


def memory():
    if os.name != 'nt':
        return {'available': False}
    from ctypes import wintypes
    class Status(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
            (key, ctypes.c_uint64) for key in ('total', 'free', 'commit_total', 'commit_free', 'virtual_total', 'virtual_free', 'extended')]
    status = Status()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return {'available': False}
    return {'available': True, 'load_percent': status.load, 'total_ram_mib': round(status.total / 2**20, 2),
            'available_ram_mib': round(status.free / 2**20, 2), 'available_commit_mib': round(status.commit_free / 2**20, 2)}


def error_code(exc):
    code = getattr(exc, 'code', None)
    if code in {'browser_capture_unavailable', 'browser_timeout', 'browser_closed', 'browser_failed'}:
        return code
    message = str(exc)
    if 'Page.captureScreenshot' in message and 'Unable to capture screenshot' in message:
        return 'browser_capture_unavailable'
    if type(exc).__name__ == 'TimeoutError':
        return 'browser_timeout'
    return 'browser_failed'


def worker(case):
    sys.path.insert(0, str(ROOT))
    from PIL import Image, ImageChops
    from playwright.sync_api import BrowserType, Page, Error
    from sight_core.capability_worker import browser
    started = time.monotonic()
    evidence = {'case': case, 'memory_before': memory(), 'capture_calls': 0, 'events': [], 'passed': False}
    original_launch, original_capture = BrowserType.launch, Page.screenshot

    def launch(self, **kwargs):
        evidence['launch_options'] = kwargs.copy()
        native = original_launch(self, **kwargs)
        evidence['browser_version'] = native.version
        native.on('disconnected', lambda *args: evidence['events'].append({'event': 'browser_disconnected', 'seconds': round(time.monotonic()-started, 3)}))
        session = native.new_browser_cdp_session()
        try:
            arguments = session.send('Browser.getBrowserCommandLine')['arguments']
            evidence['no_sandbox_flag_absent'] = '--no-sandbox' not in arguments
        except Error:
            # Production does not enable this optional diagnostic CDP method.
            # Preserve its actual launch flags instead of modifying them to probe.
            evidence['command_line_probe'] = 'unavailable'
        finally:
            session.detach()
        return native

    def capture(self, **kwargs):
        evidence['capture_calls'] += 1
        evidence['capture_options'] = kwargs.copy()
        self.on('crash', lambda *args: evidence['events'].append({'event': 'page_crash', 'seconds': round(time.monotonic()-started, 3)}))
        evidence['before_capture'] = {'memory': memory(), 'page_closed': self.is_closed(),
                                      'browser_connected': self.context.browser.is_connected(), 'viewport': self.viewport_size}
        try:
            return original_capture(self, **kwargs)
        except Exception as exc:
            evidence['capture_failure'] = {'code': error_code(exc), 'memory': memory(), 'page_closed': self.is_closed(),
                                            'browser_connected': self.context.browser.is_connected()}
            raise
        finally:
            evidence['memory_after_capture'] = memory()

    BrowserType.launch, Page.screenshot = launch, capture
    try:
        result = browser(CASES[case])
        png = base64.b64decode(result['screenshot'], validate=True)
        with Image.open(io.BytesIO(png)) as decoded:
            rgb = decoded.convert('RGB')
            nonblank = ImageChops.difference(rgb, Image.new('RGB', rgb.size, 'white')).getbbox() is not None
            evidence['image'] = {'bytes': len(png), 'sha256': hashlib.sha256(png).hexdigest(), 'size': list(rgb.size), 'nonblank': nonblank}
        evidence['security'] = {key: result[key] for key in ('network_allowed', 'scripts_enabled', 'submitted', 'blocked_requests')}
        evidence['passed'] = (evidence['image']['size'] == [1024, 768] and nonblank and
            result['fields'] == CASES[case]['fields'] and result['title'] != 'SCRIPT_RAN' and
            not result['network_allowed'] and not result['scripts_enabled'] and not result['submitted'] and
            evidence['launch_options'].get('chromium_sandbox') is True and
            evidence.get('no_sandbox_flag_absent') is not False and
            (case != 'blocked_content' or result['blocked_requests'] >= 1))
    except Exception as exc:
        evidence['error_code'] = error_code(exc)
        evidence['error_type'] = type(exc).__name__
        # Never retain raw exception text, protocol logs, page text or field values.
    finally:
        evidence['seconds'] = round(time.monotonic()-started, 3)
        evidence['memory_after'] = memory()
        print(json.dumps(evidence), flush=True)
    return 0 if evidence['passed'] else 1


def run(destination, rounds):
    if destination.exists():
        raise ValueError('Use a new evidence path; prior attempts must be preserved')
    destination.parent.mkdir(parents=True, exist_ok=True)
    from importlib.metadata import version
    result = {'started_utc': datetime.now(timezone.utc).isoformat(), 'rounds': rounds, 'cases': list(CASES),
              'plan': 'Each fixed synthetic case in each round gets one fresh process, 25-second process deadline, no retries. No artificial resource exhaustion or model inference.',
              'runtime': {'python': sys.version, 'playwright': version('playwright')},
              'source_hashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__), ROOT/'sight_core/capability_worker.py']},
              'attempts': [], 'complete': False}
    def save():
        destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    save()
    for repeat in range(rounds):
        for case in CASES:
            recorded = False
            process = subprocess.Popen([sys.executable, '-B', str(Path(__file__)), '--worker', case], cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                **({'creationflags': 0x08000000} if os.name == 'nt' else {'start_new_session': True}))
            try:
                stdout, _ = process.communicate(timeout=25)
                try:
                    row = json.loads(stdout)
                except (ValueError, TypeError):
                    row = {'case': case, 'passed': False, 'error_code': 'worker_protocol_error'}
                row['exit_code'] = process.returncode
                row['passed'] = row['passed'] and process.returncode == 0
            except subprocess.TimeoutExpired:
                row = {'case': case, 'round': repeat+1, 'passed': False, 'error_code': 'worker_timeout',
                       'memory_at_deadline': memory(), 'cleanup': 'pending'}
                result['attempts'].append(row)
                recorded = True
                save()  # Retain the failure even if cleanup itself fails or stalls.
                try:
                    if os.name == 'nt':
                        stopped = subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/taskkill.exe'), '/PID', str(process.pid), '/T', '/F'],
                                                 capture_output=True, timeout=10, creationflags=0x08000000)
                        if stopped.returncode != 0:raise OSError('Owned tree termination unverified')
                    else:
                        import signal
                        os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=10)
                    row['cleanup'] = 'completed'
                except (OSError, subprocess.SubprocessError):
                    row['cleanup'] = 'unverified'
                    result['aborted'] = 'owned_worker_cleanup_unverified'
                    result['finished_utc'] = datetime.now(timezone.utc).isoformat()
                    save()
                    print(json.dumps({'case': case, 'passed': False, 'error_code': row['error_code'], 'cleanup': row['cleanup']}), flush=True)
                    return 1
            row['round'] = repeat + 1
            if not recorded:result['attempts'].append(row)
            save()
            print(json.dumps({'round': repeat+1, 'case': case, 'passed': row['passed'], 'error_code': row.get('error_code')}), flush=True)
    result['complete'] = True
    result['passed_count'] = sum(row['passed'] for row in result['attempts'])
    result['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save()
    return 0 if result['passed_count'] == len(result['attempts']) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--rounds', type=int, choices=range(1, 11), default=10)
    parser.add_argument('--worker', choices=CASES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(worker(args.worker))
    if args.output is None:
        parser.error('--output is required')
    raise SystemExit(run(args.output.resolve(), args.rounds))
