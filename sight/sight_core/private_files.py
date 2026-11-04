"""Exclusive Windows handles for reversible edits to existing private files.

No path-based replacement/deletion while another process can replace or write
the observed file. Recovery preimages are committed before these methods run.
"""
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import os


def snapshot(stream, name):
    stat = os.fstat(stream.fileno())
    if stat.st_nlink != 1 or stat.st_size > 262144:
        raise ValueError('Linked or oversized file')
    stream.seek(0)
    data = stream.read(262145)
    if len(data) != stat.st_size:
        raise ValueError('File changed while reading')
    return {'name': name, 'content': data.decode('utf-8'), 'sha256': hashlib.sha256(data).hexdigest(),
            'identity': [stat.st_dev, stat.st_ino], 'size': stat.st_size}


@contextmanager
def exclusive_file(path):
    if os.name != 'nt':
        raise ValueError('Verified reversible file mutation currently requires Windows')
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # Deny sharing WRITE/DELETE. OPEN_REPARSE_POINT prevents following a swapped link.
    handle = kernel.CreateFileW(str(path), 0xC0010000, 1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), 'File is busy or unavailable')
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(fd, 'r+b', buffering=0) as stream:
        # stat on the opened handle, not a second path lookup.
        stat = os.fstat(stream.fileno())
        if getattr(stat, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse point rejected')
        if stat.st_nlink != 1:
            raise ValueError('Hard link rejected')
        yield stream


def replace_content(stream, content):
    data = content.encode('utf-8')
    stream.seek(0)
    remaining = memoryview(data)
    while remaining:
        written = stream.write(remaining)
        if not written:
            raise OSError('Incomplete write')
        remaining = remaining[written:]
    stream.truncate(len(data))
    os.fsync(stream.fileno())


def delete_open_file(stream):
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel.SetFileInformationByHandle.restype = wintypes.BOOL
    flag = wintypes.BOOL(True)
    if not kernel.SetFileInformationByHandle(msvcrt.get_osfhandle(stream.fileno()), 4, ctypes.byref(flag), ctypes.sizeof(flag)):
        raise OSError(ctypes.get_last_error(), 'File removal failed')
