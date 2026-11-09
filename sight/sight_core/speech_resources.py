"""Windows resource limits for the optional fixed ASR child; no device capture."""
import ctypes
from ctypes import wintypes
import os


class MemoryStatus(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD),
                *[(name, ctypes.c_ulonglong) for name in ('total', 'available', 'page_total', 'page_available',
                                                         'virtual_total', 'virtual_available', 'extended')]]


def available_memory():
    if os.name != 'nt':
        raise OSError('Windows resource query unavailable')
    state = MemoryStatus()
    state.length = ctypes.sizeof(state)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(state)):
        raise OSError('Windows resource query failed')
    return state.available


class BasicLimits(ctypes.Structure):
    _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                ('flags', wintypes.DWORD), ('working_min', ctypes.c_size_t), ('working_max', ctypes.c_size_t),
                ('active_processes', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]


class IOCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IOCounters), ('process_memory', ctypes.c_size_t),
                ('job_memory', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]


class ProcessBudget:
    def __init__(self, process, memory_bytes):
        if os.name != 'nt' or not 16 * 1024**2 <= memory_bytes <= 2 * 1024**3:
            raise OSError('Invalid Windows recognition resource budget')
        kernel = self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('Recognition job could not be created')
        limits = ExtendedLimits()
        # KILL_ON_JOB_CLOSE, PROCESS_MEMORY, ACTIVE_PROCESS. Native recognizers
        # need threads, not child processes. This is containment, not a sandbox.
        limits.basic.flags = 0x2000 | 0x100 | 0x8
        limits.basic.active_processes = 1
        limits.process_memory = memory_bytes
        if not (kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits))
                and kernel.AssignProcessToJobObject(self.handle, wintypes.HANDLE(int(process._handle)))):
            self.close()
            raise OSError('Recognition resource limits could not be enforced')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
