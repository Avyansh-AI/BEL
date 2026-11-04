import io
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from sight_core.desktop import BackendHost, DesktopBridge, DesktopController, set_autostart, dispatch_to_window
from sight_core import runtime


class Window:
    def __init__(self):
        self.calls = []
        self.on_top = False
    def __getattr__(self, name):
        return lambda *args: self.calls.append((name, args))


def test_bridge_only_exposes_presentation():
    assert {name for name in dir(DesktopBridge) if not name.startswith('_')} == {'status', 'set_mode', 'close_app'}


def test_background_requires_working_tray_and_preserves_recovery_window():
    host = DesktopController(dispatch=lambda window, callback: callback())
    host.window = Window()
    with pytest.raises(RuntimeError, match='tray'):
        host.set_mode('background')
    assert host.window.calls == [] and host.mode == 'active'
    assert host.on_closing() is True
    host.tray_ready.set()
    assert host.on_closing() is False
    deadline = time.monotonic() + 1
    while host.mode != 'background' and time.monotonic() < deadline:
        time.sleep(.005)
    assert ('hide', ()) in host.window.calls
    assert host.status()['mode'] == 'background'
    host.set_mode('active')
    assert host.mode == 'active' and ('show', ()) in host.window.calls


def test_compact_and_exit_never_stop_backend_on_hide():
    host = DesktopController(dispatch=lambda window, callback: callback())
    host.window = Window()
    host.set_mode('compact')
    assert host.window.on_top and ('resize', (380, 480)) in host.window.calls
    host.close_app()
    assert host.quitting and host.on_closing() is True
    with pytest.raises(RuntimeError):
        host.set_mode('active')
    assert ('destroy', ()) in host.window.calls


def test_native_changes_are_dispatched_without_caller_lock():
    import threading
    identities = []
    host = None
    def dispatch(window, callback):
        def run():
            assert host.lock.acquire(timeout=.5), 'Caller held lifecycle lock across native dispatch'
            host.lock.release()
            identities.append(threading.get_ident())
            callback()
        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=1)
        assert not thread.is_alive()
    host = DesktopController(dispatch=dispatch)
    host.window = Window()
    caller = threading.get_ident()
    host.set_mode('compact')
    host.close_app()
    assert len(identities) == 2 and all(identity != caller for identity in identities)
    assert host.mode == 'compact' and host.quitting


def test_queued_native_operation_expires_before_late_execution(monkeypatch):
    from types import SimpleNamespace
    pending, changed = [], []
    native = SimpleNamespace(IsDisposed=False, InvokeRequired=True, BeginInvoke=pending.append)
    window = SimpleNamespace(native=native)
    monkeypatch.setattr('sight_core.desktop._winforms_action', lambda callback: callback)
    with pytest.raises(RuntimeError, match='deadline'):
        dispatch_to_window(window, lambda: changed.append('unexpected late action'), timeout=.01)
    pending[0]()
    assert changed == []


def test_native_callback_error_propagates_and_does_not_claim_success(monkeypatch):
    import threading
    from types import SimpleNamespace
    def enqueue(callback):
        threading.Thread(target=callback).start()
    native = SimpleNamespace(IsDisposed=False, InvokeRequired=True, BeginInvoke=enqueue)
    monkeypatch.setattr('sight_core.desktop._winforms_action', lambda callback: callback)
    def unavailable():
        raise ValueError('window gone')
    with pytest.raises(ValueError, match='window gone'):
        dispatch_to_window(SimpleNamespace(native=native), unavailable)


def test_failed_close_retains_tray_and_restore_path():
    from types import SimpleNamespace
    stopped = []
    def blocked(window, callback):
        raise RuntimeError('Desktop operation exceeded its deadline')
    host = DesktopController(dispatch=blocked)
    host.window = Window()
    host.tray = SimpleNamespace(stop=lambda: stopped.append(True))
    host.tray_ready.set()
    with pytest.raises(RuntimeError, match='deadline'):
        host.close_app()
    assert stopped == [] and not host.quitting and host.status()['tray_available']
    host._dispatch = lambda window, callback: callback()
    host.set_mode('active')
    assert ('show', ()) in host.window.calls


def test_disposed_window_rejects_native_work():
    from types import SimpleNamespace
    native = SimpleNamespace(IsDisposed=True)
    called = []
    with pytest.raises(RuntimeError, match='not ready'):
        dispatch_to_window(SimpleNamespace(native=native), lambda: called.append(True))
    assert called == []


@pytest.mark.parametrize('bad', ['shell', '../skill_worker.py', 'SIGHT', ''])
def test_arbitrary_worker_is_rejected(bad):
    with pytest.raises(ValueError):
        runtime.worker_command(bad)


def test_source_worker_keeps_isolation():
    command = runtime.worker_command('skill')
    assert command[:3] == [sys.executable, '-I', '-S']
    completed = subprocess.run(command, input=json.dumps({'text':'  hello  ','operations':[{'op':'trim'},{'op':'upper'}]}),
                               capture_output=True, text=True, timeout=3)
    assert completed.returncode == 0 and json.loads(completed.stdout)['result'] == 'HELLO'


def test_packaged_worker_uses_console_sibling_or_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'BEL.exe'))
    with pytest.raises(RuntimeError, match='missing'):
        runtime.worker_command('skill')
    (tmp_path / 'BEL-worker.exe').write_bytes(b'test fixture, not executable')
    assert runtime.worker_command('needle', '--assets', 'reviewed') == [str(tmp_path / 'BEL-worker.exe'), '--worker', 'needle', '--assets', 'reviewed']


def test_fixed_dispatch_rejects_python_options_and_unknown_worker():
    assert runtime.dispatch_worker(['-c', 'anything']) == 2
    assert runtime.dispatch_worker(['--worker', 'arbitrary']) == 2
    assert runtime.dispatch_worker(['--worker', 'skill', '--code', 'anything']) == 2


def test_fixed_dispatch_real_subprocess():
    entry = Path(__file__).resolve().parents[1] / 'scripts' / 'bel_worker.py'
    result = subprocess.run([sys.executable, str(entry), '--worker', 'skill'],
        input=json.dumps({'text':'hi','operations':[{'op':'prefix','value':'BEL: '}]}), capture_output=True, text=True, timeout=3)
    assert result.returncode == 0 and json.loads(result.stdout) == {'ok':True,'result':'BEL: hi'}


def test_autostart_is_not_enabled_from_source():
    with pytest.raises(RuntimeError, match='packaged'):
        set_autostart(True)


def test_backend_port_collision_does_not_attach_to_or_stop_existing_server(tmp_path):
    import socket
    from sight_core.config import Config
    existing = socket.socket()
    existing.bind(('127.0.0.1', 0))
    existing.listen(1)
    try:
        host = BackendHost(Config(tmp_path, port=existing.getsockname()[1]))
        with pytest.raises(OSError):
            host.start()
        assert existing.fileno() != -1
        assert not (tmp_path / 'sight.sqlite3').exists()
    finally:
        existing.close()
