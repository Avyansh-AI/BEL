"""Explicit own-window lifecycle stress diagnostic; no audio or tool actions."""
import argparse
import faulthandler
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'sight'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=20)
    args = parser.parse_args()
    if os.name != 'nt' or not 1 <= args.cycles <= 100:
        raise SystemExit('Windows and 1..100 cycles required')
    args.output.mkdir(parents=True, exist_ok=False)
    trace = (args.output / 'thread-trace.txt').open('w')
    faulthandler.dump_traceback_later(20, file=trace, exit=True)
    from sight_core import desktop
    record = {'kind': 'source_native_modes', 'cycles': args.cycles, 'completed': 0, 'steps': []}
    def step(name):
        record['steps'].append({'name': name, 'at': round(time.monotonic(), 4), 'thread': threading.get_ident()})
        (args.output / 'progress.json').write_text(json.dumps(record, indent=2))
        faulthandler.cancel_dump_traceback_later()
        faulthandler.dump_traceback_later(15, file=trace, exit=True)
    class WindowProxy:
        def __init__(self, real):
            object.__setattr__(self, '_real', real)
        def __getattr__(self, name):
            value = getattr(self._real, name)
            if not callable(value):
                return value
            def wrapped(*arguments, **kwargs):
                step(name + '.begin')
                result = value(*arguments, **kwargs)
                step(name + '.end')
                return result
            return wrapped
        def __setattr__(self, name, value):
            step(name + '.begin')
            setattr(self._real, name, value)
            step(name + '.end')
    def probe(controller, host, report, started):
        controller.window = WindowProxy(controller.window)
        controller.tray_ready.wait(5)
        try:
            for n in range(args.cycles):
                for mode in ('compact', 'background', 'active'):
                    step(f'cycle.{n}.{mode}')
                    controller.set_mode(mode)
                record['completed'] += 1
            controller.smoke_passed = True
            record['status'] = 'PASS'
        except Exception as exc:
            controller.smoke_passed = False
            record['status'], record['error_type'] = 'FAIL', type(exc).__name__
        finally:
            (args.output / 'result.json').write_text(json.dumps(record, indent=2))
            controller.close_app()
    desktop.smoke_probe = probe
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    code = desktop.main(['--data-directory', str(args.output / 'synthetic-data'), '--port', str(port),
                         '--smoke-test', str(args.output / 'native.json')])
    faulthandler.cancel_dump_traceback_later()
    trace.close()
    return code


if __name__ == '__main__':
    raise SystemExit(main())
