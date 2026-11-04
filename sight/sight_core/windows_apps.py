"""Observed application launch/focus for two owner-reviewed Windows targets.

Independent Win32 implementation. No titles, screenshots, input injection,
arbitrary executable paths, process termination or unsaved-work dismissal.
Inspection failure is unknown, never evidence that an app is absent.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
from pathlib import Path, PureWindowsPath
import subprocess
import time


NAMES = {'notepad': {'notepad.exe'}, 'calculator': {'calculatorapp.exe', 'calculator.exe', 'calc.exe'}}
LAUNCHERS = {'notepad': 'notepad.exe', 'calculator': 'calc.exe'}
PACKAGE_PREFIX = {'notepad': 'microsoft.windowsnotepad_', 'calculator': 'microsoft.windowscalculator_'}


class InspectionError(ValueError):
    pass


@dataclass(frozen=True)
class Observation:
    pids: tuple[int, ...]
    windows: tuple[tuple[int, int], ...]  # (pid, HWND), never window text


def trusted_image(application, image, system_root, program_files):
    """Match fixed system images or the corresponding Windows Store package."""
    path = PureWindowsPath(image)
    if application not in NAMES or path.name.lower() not in NAMES[application]:
        return False
    root, packages = PureWindowsPath(system_root), PureWindowsPath(program_files) / 'WindowsApps'
    try:
        relative = path.relative_to(root)
        if len(relative.parts) == 2 and relative.parts[0].lower() in {'system32', 'syswow64'}:
            return True
    except ValueError:
        pass
    try:
        relative = path.relative_to(packages)
        return len(relative.parts) >= 2 and relative.parts[0].lower().startswith(PACKAGE_PREFIX[application])
    except ValueError:
        return False


class WindowsBackend:
    def __init__(self):
        if os.name != 'nt':
            raise InspectionError('Windows desktop session required')
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.system_root = os.environ.get('SystemRoot', 'C:/Windows')
        self.program_files = os.environ.get('ProgramFiles', 'C:/Program Files')
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        class ProcessEntry(ctypes.Structure):
            _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                       ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                       ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                       ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', wintypes.LONG),
                       ('dwFlags', wintypes.DWORD), ('szExeFile', wintypes.WCHAR * 260)]
        self.entry_type = ProcessEntry
        self.kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        for name in ('Process32FirstW', 'Process32NextW'):
            method = getattr(self.kernel, name)
            method.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
            method.restype = wintypes.BOOL
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                         wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.user.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.user.EnumWindows.restype = wintypes.BOOL
        self.user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user.GetWindowThreadProcessId.restype = wintypes.DWORD
        for name in ('IsWindowVisible', 'IsWindow', 'SetForegroundWindow'):
            method = getattr(self.user, name)
            method.argtypes, method.restype = [wintypes.HWND], wintypes.BOOL
        self.user.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.ShowWindowAsync.restype = wintypes.BOOL
        self.user.GetForegroundWindow.argtypes = []
        self.user.GetForegroundWindow.restype = wintypes.HWND

    def _image(self, pid):
        handle = self.kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION only
        if not handle:
            raise InspectionError('Application identity could not be inspected')
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not self.kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                raise InspectionError('Application identity could not be inspected')
            return buffer.value
        finally:
            self.kernel.CloseHandle(handle)

    def inspect(self, application):
        if application not in NAMES:
            raise ValueError('Select an allowlisted application')
        snapshot = self.kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise InspectionError('Application enumeration failed')
        candidates = set()
        try:
            entry = self.entry_type()
            entry.dwSize = ctypes.sizeof(entry)
            if not self.kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
                raise InspectionError('Application enumeration failed')
            while True:
                if entry.szExeFile.lower() in NAMES[application]:
                    pid = int(entry.th32ProcessID)
                    if pid != os.getpid():
                        image = self._image(pid)
                        if trusted_image(application, image, self.system_root, self.program_files):
                            candidates.add(pid)
                        else:
                            # A matching process name at an unexpected path is not safe
                            # evidence of absence and must not be focused or duplicated.
                            raise InspectionError('Application identity is outside allowed locations')
                if not self.kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                    if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                        raise InspectionError('Application enumeration incomplete')
                    break
        finally:
            self.kernel.CloseHandle(snapshot)
        windows = []
        @self.callback_type
        def visit(hwnd, _):
            if self.user.IsWindowVisible(hwnd):
                pid = wintypes.DWORD()
                self.user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value in candidates:
                    windows.append((pid.value, int(hwnd)))
            return True
        if not self.user.EnumWindows(visit, 0):
            raise InspectionError('Window enumeration failed')
        return Observation(tuple(sorted(candidates)), tuple(windows))

    def focus(self, application, pid, hwnd):
        # Revalidate immediately before a presentation change: an HWND can be reused.
        observation = self.inspect(application)
        if (pid, hwnd) not in observation.windows:
            return False
        self.user.ShowWindowAsync(hwnd, 9)  # SW_RESTORE, never a close message
        self.user.SetForegroundWindow(hwnd)
        return self.user.GetForegroundWindow() == hwnd

    def launch(self, application):
        executable = Path(self.system_root) / 'System32' / LAUNCHERS[application]
        # GUI target only, no shell, arguments or command interpolation.
        return subprocess.Popen([str(executable)], shell=False).pid


def open_application(application, *, backend=None, timeout=6.0, clock=time.monotonic, sleep=time.sleep):
    """Return observed evidence; a process start alone is never verified success."""
    if application not in NAMES:
        raise ValueError('Select an allowlisted application')
    if not 0.1 <= timeout <= 10:
        raise ValueError('Application verification deadline must be 0.1–10 seconds')
    backend = backend or WindowsBackend()
    before = backend.inspect(application)
    if before.windows:
        pid, hwnd = before.windows[0]
        focused = backend.focus(application, pid, hwnd)
        return {'ok': True, 'application': application, 'pid': pid, 'reused': True,
                'running_verified': True, 'window_verified': True, 'focus_verified': focused,
                'gui_verified': focused, 'reason': 'existing_window_focused' if focused else 'foreground_not_verified'}
    if before.pids:
        # Includes suspended/starting apps and applications whose window is hosted
        # by a broker. Do not create a duplicate simply because no HWND is visible.
        return {'ok': True, 'application': application, 'pid': before.pids[0], 'reused': True,
                'running_verified': True, 'window_verified': False, 'focus_verified': False,
                'gui_verified': False, 'reason': 'running_without_verified_window'}
    pid = backend.launch(application)
    deadline = clock() + timeout
    while clock() < deadline:
        try:
            observed = backend.inspect(application)
        except InspectionError:
            return {'ok': True, 'application': application, 'pid': pid, 'reused': False,
                    'gui_verified': False, 'reason': 'post_launch_inspection_unavailable'}
        if observed.windows:
            observed_pid, hwnd = observed.windows[0]
            focused = backend.focus(application, observed_pid, hwnd)
            return {'ok': True, 'application': application, 'pid': observed_pid, 'launcher_pid': pid,
                    'reused': False, 'running_verified': True, 'window_verified': True,
                    'focus_verified': focused, 'gui_verified': True, 'reason': 'window_observed'}
        sleep(.1)
    return {'ok': True, 'application': application, 'pid': pid, 'reused': False,
            'gui_verified': False, 'reason': 'window_deadline_exceeded'}
