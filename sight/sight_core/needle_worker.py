"""Fixed Needle C-API worker. No tool execution, networking or Python plugins.

Source launch: python -I -S needle_worker.py --assets <verified asset directory>.
Packaged launch dispatches the hidden console BEL-worker.exe --worker needle.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import importlib.util
import json
import os
from pathlib import Path
import platform
import sys
import time


def _adapter():
    if getattr(sys, "frozen", False):
        from sight_core import needle
        return needle
    # -I/-S excludes working-directory packages and environment/site hooks.
    spec = importlib.util.spec_from_file_location("bel_fixed_needle_adapter", Path(__file__).with_name("needle.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def locked_library(path: Path, adapter):
    """Keep the verified DLL immutable from verification through native use.

    Windows denies replacement and write opens while this handle is held.
    Hashing a pathname and loading it later without a lock has a race window.
    """
    adapter._plain_path(path)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    # GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT.
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise adapter.NeedleError("assets_unavailable")
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def complete(root: Path, request: dict, adapter) -> dict:
    if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise adapter.NeedleError("unsupported_platform")
    if (not isinstance(request, dict) or set(request) != {"text", "tools", "max_new_tokens"}
            or not isinstance(request["text"], str) or not request["text"].strip()
            or "\x00" in request["text"] or len(request["text"].encode()) > adapter.MAX_INPUT_BYTES
            or type(request["max_new_tokens"]) is not int or not 32 <= request["max_new_tokens"] <= 256):
        raise adapter.NeedleError("invalid_request")
    tools = adapter.normalize_tools(request["tools"])
    started = time.monotonic()
    with locked_library(root / "libneedle3.dll", adapter):
        return _infer(root, request, adapter, tools, started)


def _infer(root, request, adapter, tools, started):
    adapter.verify_assets(root)
    weights = adapter.read_verified_asset(root, "needle3.cact")
    # Restrict dependent-DLL lookup to System32; absolute verified DLL is loaded.
    try:
        runtime = ctypes.CDLL(str(root / "libneedle3.dll"), winmode=0x00000800)
    except OSError as exc:
        raise adapter.NeedleError("runtime_unavailable") from exc
    runtime.needle_load.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_ulonglong]
    runtime.needle_load.restype = ctypes.c_int
    runtime.needle_models.argtypes, runtime.needle_models.restype = [], ctypes.c_int
    runtime.needle_last_error.argtypes, runtime.needle_last_error.restype = [], ctypes.c_char_p
    runtime.needle_init.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
    runtime.needle_init.restype = ctypes.c_int
    runtime.needle_complete.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int,
                                       ctypes.c_int, ctypes.POINTER(ctypes.c_char), ctypes.c_int]
    runtime.needle_complete.restype = ctypes.c_int
    runtime.needle_reset.argtypes, runtime.needle_reset.restype = [], None
    buffer = (ctypes.c_ubyte * len(weights)).from_buffer_copy(weights)
    if runtime.needle_load(buffer, len(weights)) < 0 or not runtime.needle_models() & 1:
        raise adapter.NeedleError("model_load_failed")
    prefix = runtime.needle_init(adapter.SYSTEM_PROMPT.encode(), json.dumps(tools, ensure_ascii=True).encode(), None)
    if prefix < 0:
        raise adapter.NeedleError("model_init_failed")
    # A byte is an upper bound on one tokenizer byte-fallback token. Reserve
    # room conservatively instead of silently truncating a complex request.
    if prefix + len(request["text"].encode()) + request["max_new_tokens"] + 64 > 8192:
        raise adapter.NeedleError("context_overflow")
    loaded = time.monotonic()
    runtime.needle_reset()
    output = ctypes.create_string_buffer(adapter.MAX_OUTPUT_BYTES)
    result = runtime.needle_complete(request["text"].encode(), None, 0, request["max_new_tokens"],
                                     output, len(output))
    if result < 0:
        raise adapter.NeedleError("model_complete_failed")
    response = adapter.strict_json(output.value)
    if not isinstance(response, dict):
        raise adapter.NeedleError("invalid_json")
    return {"ok": True, "response": response,
            "timings": {"load_ms": round((loaded - started) * 1000, 3),
                        "inference_ms": round((time.monotonic() - loaded) * 1000, 3)}}


def main(argv=None):
    os.environ.update(NEEDLE_TELEMETRY="0", DO_NOT_TRACK="1", HF_HUB_OFFLINE="1")
    parser = argparse.ArgumentParser(description="BEL fixed proposal-only Needle worker")
    parser.add_argument("--assets", required=True, type=Path)
    args = parser.parse_args(argv)
    adapter = _adapter()
    try:
        raw = sys.stdin.buffer.read(adapter.MAX_REQUEST_BYTES + 1)
        if len(raw) > adapter.MAX_REQUEST_BYTES:
            raise adapter.NeedleError("invalid_request")
        result = complete(args.assets.absolute(), adapter.strict_json(raw), adapter)
    except adapter.NeedleError as exc:
        result = {"ok": False, "reason": str(exc)}
    except Exception:
        result = {"ok": False, "reason": "worker_failed"}
    encoded = json.dumps(result, allow_nan=False, ensure_ascii=True)
    if len(encoded.encode()) > adapter.MAX_OUTPUT_BYTES:
        encoded = '{"ok":false,"reason":"worker_failed"}'
    sys.stdout.write(encoded)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
