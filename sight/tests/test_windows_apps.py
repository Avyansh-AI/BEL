import os

import pytest

from sight_core.windows_apps import InspectionError, Observation, WindowsBackend, open_application, trusted_image


class Backend:
    def __init__(self, observations, focused=True):
        self.observations = iter(observations)
        self.last = Observation((), ())
        self.focused = focused
        self.launches = []
        self.focus_calls = []

    def inspect(self, application):
        self.last = next(self.observations, self.last)
        if isinstance(self.last, Exception):
            raise self.last
        return self.last

    def focus(self, *args):
        self.focus_calls.append(args)
        return self.focused

    def launch(self, application):
        self.launches.append(application)
        return 42


def test_existing_application_is_focused_without_duplicate():
    backend = Backend([Observation((7,), ((7, 8),))])
    result = open_application('notepad', backend=backend)
    assert result['gui_verified'] and result['reused']
    assert backend.launches == []
    assert backend.focus_calls == [('notepad', 7, 8)]


def test_focus_refused_does_not_claim_success_or_relaunch():
    backend = Backend([Observation((7,), ((7, 8),))], focused=False)
    result = open_application('notepad', backend=backend)
    assert not result['gui_verified'] and result['window_verified']
    assert backend.launches == []


def test_running_process_without_visible_window_is_not_duplicated():
    backend = Backend([Observation((7,), ())])
    result = open_application('calculator', backend=backend)
    assert not result['gui_verified'] and result['running_verified']
    assert backend.launches == []


def test_inspection_failure_is_unknown_not_absent():
    backend = Backend([InspectionError('access denied')])
    with pytest.raises(InspectionError):
        open_application('notepad', backend=backend)
    assert backend.launches == []


def test_verified_launch_observes_window_even_if_broker_pid_changes():
    backend = Backend([Observation((), ()), Observation((44,), ((44, 88),))])
    result = open_application('calculator', backend=backend)
    assert result['gui_verified'] and not result['reused']
    assert result['pid'] == 44 and result['launcher_pid'] == 42
    assert backend.launches == ['calculator']


def test_post_launch_inspection_failure_is_unverified_and_not_retried():
    backend = Backend([Observation((), ()), InspectionError('failed')])
    result = open_application('notepad', backend=backend)
    assert not result['gui_verified']
    assert backend.launches == ['notepad']


def test_pid_without_window_reaches_bounded_deadline():
    backend = Backend([Observation((), ()), Observation((42,), ())])
    times = iter([0, 0, .1, .2, .3])
    result = open_application('notepad', backend=backend, timeout=.2, clock=lambda: next(times), sleep=lambda _: None)
    assert not result['gui_verified'] and result['reason'] == 'window_deadline_exceeded'
    assert backend.launches == ['notepad']


@pytest.mark.parametrize('name', ['chrome', 'BEL', 'powershell', '../notepad', 'notepad.exe /x'])
def test_unknown_target_never_reaches_backend(name):
    backend = Backend([])
    with pytest.raises(ValueError):
        open_application(name, backend=backend)
    assert not backend.launches


@pytest.mark.parametrize('image,expected', [
    (r'C:\Windows\System32\notepad.exe', True),
    (r'C:\Windows\SysWOW64\notepad.exe', True),
    (r'C:\Program Files\WindowsApps\Microsoft.WindowsNotepad_1.0_x64__8wekyb3d8bbwe\Notepad\Notepad.exe', True),
    (r'C:\Users\Owner\Downloads\notepad.exe', False),
    (r'C:\Windows\Temp\notepad.exe', False),
    (r'C:\Program Files\WindowsApps\OtherPackage\notepad.exe', False),
    (r'C:\Windows\System32\BEL.exe', False),
])
def test_full_image_identity_rejects_spoofed_names(image, expected):
    assert trusted_image('notepad', image, r'C:\Windows', r'C:\Program Files') is expected


@pytest.mark.skipif(os.name != 'nt', reason='Win32 read-only integration')
def test_actual_win32_enumeration_is_read_only():
    backend = WindowsBackend()
    for name in ('notepad', 'calculator'):
        result = backend.inspect(name)
        assert isinstance(result, Observation)
        assert all(type(pid) is int and pid > 0 for pid in result.pids)
        assert all(pid in result.pids for pid, _ in result.windows)
