"""Offline, proposal-only Needle 3 adapter. This module never executes tools.

Assets are explicitly provisioned from one upstream revision, verified again in
the isolated worker, and never downloaded during a routing request. The caller
must apply its registry validation, permission policy, budgets and verification.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading
import time


REVISION = "d6c7d6a2e9655505e0f8e23339356dd1705900eb"
ASSET_BASE = f"https://huggingface.co/Cactus-Compute/needle3/resolve/{REVISION}/"
ASSETS = {
    "needle3.cact": (35335380, "c9d915eca282ed42d1a09b143b592adb4cc6744ffe2d294adf5cfc5548170c38"),
    "libneedle3.dll": (1533952, "1263c6003dd88b9fcb1904a55985be66858639849309280b42f7764ee5d874d0"),
    "LICENSE": (11358, "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"),
}
ENGINE_WHEEL = "python/cactus_needle-3.3.3-py3-none-win_amd64.whl"
ENGINE_WHEEL_SIZE = 700859
ENGINE_WHEEL_SHA256 = "b6447b2be7426b7ff3b06360b15a90a8b7870e3fa2275023e20541d5e8d81bdb"
MAX_INPUT_BYTES = 4096
MAX_REQUEST_BYTES = 32768
MAX_OUTPUT_BYTES = 65536
MAX_TOOLS_BYTES = 20000
# Needle's system field accepts environment facts, not behavioral instructions.
# Omit it until an owner-selected locale/date context is deliberately supported.
# Schema validation, confidence gating and human authorization live outside the
# model and remain mandatory. See upstream llms.txt, "System facts (optional)".
SYSTEM_PROMPT = ""


class NeedleError(ValueError):
    """Stable, non-sensitive error code safe for diagnostic responses."""


def finite_number(value) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def strict_json(value: str | bytes):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise NeedleError("duplicate_json_key")
            result[key] = item
        return result

    def invalid(_):
        raise NeedleError("nonfinite_json")

    try:
        return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, TypeError, RecursionError) as exc:
        raise NeedleError("invalid_json") from exc


def default_asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / 'models/needle3'
        if bundled.is_dir():
            return bundled
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "BEL" / "models" / "needle3"
    return Path(__file__).resolve().parents[2] / ".cache" / "needle3"


def expected_manifest() -> dict:
    return {
        "format": 1, "upstream": "Cactus-Compute/needle3", "revision": REVISION,
        "engine_version": "3.3.3", "platform": "windows-x86_64", "license": "Apache-2.0",
        "files": {name: {"size": size, "sha256": digest} for name, (size, digest) in ASSETS.items()},
    }


def _plain_path(path: Path):
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise NeedleError("asset_link_rejected")


def read_verified_asset(root: Path, name: str) -> bytes:
    if name not in ASSETS:
        raise NeedleError("unknown_asset")
    path = root / name
    _plain_path(path)
    size, digest = ASSETS[name]
    try:
        with path.open("rb") as stream:
            stat = os.fstat(stream.fileno())
            if stat.st_nlink != 1 or stat.st_size != size:
                raise NeedleError("asset_integrity_failed")
            data = stream.read(size + 1)
    except OSError as exc:
        raise NeedleError("assets_unavailable") from exc
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        raise NeedleError("asset_integrity_failed")
    return data


def verify_assets(root: str | Path) -> dict:
    root = Path(root).absolute()
    manifest = root / "manifest.json"
    _plain_path(manifest)
    try:
        with manifest.open("rb") as stream:
            stat = os.fstat(stream.fileno())
            if stat.st_nlink != 1:
                raise NeedleError("asset_link_rejected")
            if stat.st_size > 8192:
                raise NeedleError("asset_manifest_mismatch")
            content = strict_json(stream.read(8193))
    except OSError as exc:
        raise NeedleError("assets_unavailable") from exc
    if content != expected_manifest():
        raise NeedleError("asset_manifest_mismatch")
    for name in ASSETS:
        read_verified_asset(root, name)
    return content


_SCHEMA_KEYS = {
    "type", "properties", "required", "additionalProperties", "items", "enum", "const",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength", "maxLength",
    "minItems", "maxItems", "pattern", "description", "title", "default",
}


def _check_schema(schema, depth=0):
    if not isinstance(schema, dict) or depth > 6 or set(schema) - _SCHEMA_KEYS:
        raise NeedleError("unsupported_tool_schema")
    kind = schema.get("type")
    if kind not in {"object", "array", "string", "number", "integer", "boolean", "null"}:
        raise NeedleError("unsupported_tool_schema")
    for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"):
        if key in schema and not finite_number(schema[key]):
            raise NeedleError("unsupported_tool_schema")
    for key in ("minLength", "maxLength", "minItems", "maxItems"):
        if key in schema and (type(schema[key]) is not int or not 0 <= schema[key] <= 65536):
            raise NeedleError("unsupported_tool_schema")
    if "enum" in schema and (not isinstance(schema["enum"], list) or not 1 <= len(schema["enum"]) <= 100):
        raise NeedleError("unsupported_tool_schema")
    if "pattern" in schema:
        if not isinstance(schema["pattern"], str) or len(schema["pattern"]) > 256:
            raise NeedleError("unsupported_tool_schema")
        try:
            re.compile(schema["pattern"])
        except re.error as exc:
            raise NeedleError("unsupported_tool_schema") from exc
    if kind == "object":
        props, required = schema.get("properties", {}), schema.get("required", [])
        if (not isinstance(props, dict) or len(props) > 32 or not isinstance(required, list)
                or any(not isinstance(name, str) for name in required)
                or not set(required) <= set(props) or schema.get("additionalProperties", False) is not False):
            raise NeedleError("unsupported_tool_schema")
        for name, item in props.items():
            if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", name):
                raise NeedleError("unsupported_tool_schema")
            _check_schema(item, depth + 1)
    elif kind == "array":
        _check_schema(schema.get("items"), depth + 1)


def validate_arguments(value, schema, depth=0):
    """Conservative supported JSON Schema subset; unknown properties fail closed."""
    if depth > 6:
        raise NeedleError("invalid_arguments")
    kind = schema["type"]
    valid = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "boolean": type(value) is bool,
        "null": value is None, "integer": type(value) is int,
        "number": type(value) in (int, float),
    }[kind]
    if not valid:
        raise NeedleError("invalid_arguments")
    if "enum" in schema and not any(type(value) is type(item) and value == item for item in schema["enum"]):
        raise NeedleError("invalid_arguments")
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise NeedleError("invalid_arguments")
    if kind == "object":
        props = schema.get("properties", {})
        if set(value) - set(props) or set(schema.get("required", [])) - set(value):
            raise NeedleError("invalid_arguments")
        for name, item in value.items():
            validate_arguments(item, props[name], depth + 1)
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= min(schema.get("maxItems", 32), 32):
            raise NeedleError("invalid_arguments")
        for item in value:
            validate_arguments(item, schema["items"], depth + 1)
    elif kind == "string":
        if "\x00" in value or not schema.get("minLength", 0) <= len(value) <= min(schema.get("maxLength", 4096), 4096):
            raise NeedleError("invalid_arguments")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            raise NeedleError("invalid_arguments")
    elif kind in {"number", "integer"}:
        if not finite_number(value) or value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise NeedleError("invalid_arguments")
        if value <= schema.get("exclusiveMinimum", -math.inf) or value >= schema.get("exclusiveMaximum", math.inf):
            raise NeedleError("invalid_arguments")


def normalize_tools(tools: list[dict]) -> list[dict]:
    if not isinstance(tools, list) or not 1 <= len(tools) <= 12:
        raise NeedleError("unsupported_tools")
    normalized, names = [], set()
    for original in tools:
        if not isinstance(original, dict):
            raise NeedleError("unsupported_tools")
        tool = original.get("function") if original.get("type") == "function" else original
        if not isinstance(tool, dict) or set(tool) - {"name", "description", "parameters", "strict"}:
            raise NeedleError("unsupported_tools")
        name, description = tool.get("name"), tool.get("description", "")
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,79}", name)
                or name in names or not isinstance(description, str) or len(description) > 1000):
            raise NeedleError("unsupported_tools")
        schema = tool.get("parameters")
        _check_schema(schema)
        if schema["type"] != "object":
            raise NeedleError("unsupported_tool_schema")
        names.add(name)
        normalized.append({"name": name, "description": description, "parameters": schema})
    try:
        encoded = json.dumps(normalized, allow_nan=False, ensure_ascii=True).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise NeedleError("unsupported_tool_schema") from exc
    if len(encoded) > MAX_TOOLS_BYTES or b"\\u0000" in encoded:
        raise NeedleError("tool_context_overflow")
    return strict_json(encoded)


def fallback(reason: str, confidence=None, timings=None) -> dict:
    return {"status": "fallback", "calls": [], "confidence": confidence, "reason": reason, "timings": timings or {}}


def parse_proposal(raw, tools, minimum_confidence=0.7, max_calls=1) -> dict:
    """The model's confidence is evidence, never permission to execute."""
    if not isinstance(raw, dict):
        return fallback("invalid_response")
    timings = {}
    for key in ("prefill_tps", "decode_tps", "peak_ram_mb"):
        value = raw.get(key)
        if finite_number(value) and 0 <= value < 1e9:
            timings[key] = value
    confidence = raw.get("confidence")
    if not finite_number(confidence) or not 0 <= confidence <= 1:
        return fallback("unknown_confidence", timings=timings)
    if raw.get("success") is False or raw.get("error") or raw.get("error_code"):
        return fallback("model_error", confidence, timings)
    validation = raw.get("validation", {})
    if not isinstance(validation, dict) or validation.get("ungrounded"):
        return fallback("ungrounded_arguments", confidence, timings)
    if confidence < minimum_confidence:
        return fallback("low_confidence", confidence, timings)
    calls = raw.get("function_calls")
    if not calls:
        return fallback("no_supported_call", confidence, timings)
    if not isinstance(calls, list) or not 1 <= len(calls) <= max_calls:
        return fallback("call_budget_exceeded", confidence, timings)
    schemas = {tool["name"]: tool["parameters"] for tool in tools}
    accepted, seen = [], set()
    for call in calls:
        if not isinstance(call, dict) or set(call) - {"name", "arguments"}:
            return fallback("invalid_call", confidence, timings)
        name = call.get("name")
        if not isinstance(name, str) or name not in schemas:
            return fallback("unknown_tool", confidence, timings)
        args = call.get("arguments", {})
        try:
            validate_arguments(args, schemas[name])
            key = json.dumps([name, args], sort_keys=True, allow_nan=False, ensure_ascii=True)
        except (ValueError, TypeError, RecursionError):
            return fallback("invalid_arguments", confidence, timings)
        if key in seen:
            return fallback("duplicate_call", confidence, timings)
        seen.add(key)
        accepted.append({"name": name, "arguments": args})
    return {"status": "proposed", "calls": accepted, "confidence": confidence,
            "reason": "requires_policy_review", "timings": timings}


def worker_command(asset_dir: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        from .runtime import worker_command as fixed_worker
        return fixed_worker("needle", "--assets", str(asset_dir))
    return [sys.executable, "-I", "-S", str(Path(__file__).with_name("needle_worker.py")), "--assets", str(asset_dir)]


def _run_worker(command: list[str], payload: bytes, deadline: float, cancelled: threading.Event) -> bytes:
    """Thread-backed pipes also work on Windows SelectorEventLoop/GUI hosts."""
    env = {key: value for key, value in os.environ.items() if key.upper() in {
        "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE",
    }}
    env.update(NEEDLE_TELEMETRY="0", DO_NOT_TRACK="1", HF_HUB_OFFLINE="1", PYTHONUTF8="1")
    process = None
    threads = []
    overflow = threading.Event()
    stdout = bytearray()
    try:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=env, shell=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)

        def drain(stream, limit, output=None):
            count = 0
            try:
                while chunk := stream.read(4096):
                    count += len(chunk)
                    if count > limit:
                        overflow.set()
                        break
                    if output is not None:
                        output.extend(chunk)
            except OSError:
                pass

        def send():
            try:
                process.stdin.write(payload)
                process.stdin.close()
            except (OSError, ValueError):
                pass

        for target, args in ((drain, (process.stdout, MAX_OUTPUT_BYTES, stdout)),
                             (drain, (process.stderr, 8192)), (send, ())):
            thread = threading.Thread(target=target, args=args, daemon=True)
            thread.start()
            threads.append(thread)
        while process.poll() is None:
            if cancelled.is_set():
                raise NeedleError("cancelled")
            if time.monotonic() >= deadline:
                raise NeedleError("deadline_exceeded")
            if overflow.is_set():
                raise NeedleError("worker_output_overflow")
            time.sleep(0.02)
        for thread in threads:
            thread.join(timeout=1)
        if overflow.is_set():
            raise NeedleError("worker_output_overflow")
        if process.returncode:
            raise NeedleError("worker_failed")
        return bytes(stdout)
    except OSError as exc:
        raise NeedleError("worker_unavailable") from exc
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)
            for thread in threads:
                thread.join(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()


class NeedleRouter:
    """Disposable native workers; a single in-flight proposal per router."""
    def __init__(self, asset_dir=None, *, timeout_seconds=15.0, minimum_confidence=0.7, max_calls=1):
        if not finite_number(timeout_seconds) or not 0.1 <= timeout_seconds <= 60:
            raise ValueError("Needle timeout must be between 0.1 and 60 seconds")
        if not finite_number(minimum_confidence) or not 0.1 <= minimum_confidence <= 1:
            raise ValueError("Needle confidence threshold must be between 0.1 and 1")
        if type(max_calls) is not int or not 1 <= max_calls <= 4:
            raise ValueError("Needle max_calls must be between 1 and 4")
        self.asset_dir = Path(asset_dir or default_asset_dir()).absolute()
        self.timeout_seconds = timeout_seconds
        self.minimum_confidence = minimum_confidence
        self.max_calls = max_calls
        self._busy = threading.Lock()

    async def propose(self, text: str, tools: list[dict]) -> dict:
        started = time.monotonic()
        if (not isinstance(text, str) or not text.strip() or "\x00" in text
                or len(text.encode("utf-8", errors="replace")) > MAX_INPUT_BYTES):
            return fallback("input_overflow_or_invalid")
        try:
            normalized = normalize_tools(tools)
            payload = json.dumps({"text": text, "tools": normalized, "max_new_tokens": 256},
                                 ensure_ascii=True, allow_nan=False).encode()
            if len(payload) > MAX_REQUEST_BYTES:
                return fallback("request_overflow")
        except (NeedleError, TypeError, ValueError, RecursionError) as exc:
            return fallback(str(exc) if isinstance(exc, NeedleError) else "invalid_request")
        if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
            return fallback("unsupported_platform")
        if not self._busy.acquire(blocking=False):
            return fallback("router_busy")
        cancelled = threading.Event()
        worker_task = None
        try:
            # The worker verifies the manifest and every digest before loading.
            worker_task = asyncio.create_task(asyncio.to_thread(
                _run_worker, worker_command(self.asset_dir), payload, started + self.timeout_seconds, cancelled))
            raw = await asyncio.shield(worker_task)
            envelope = strict_json(raw)
            if not isinstance(envelope, dict):
                raise NeedleError("invalid_worker_response")
            if envelope.get("ok") is not True:
                allowed = {"assets_unavailable", "asset_integrity_failed", "asset_manifest_mismatch",
                           "asset_link_rejected", "runtime_unavailable", "model_load_failed",
                           "model_init_failed", "model_complete_failed", "context_overflow",
                           "invalid_json", "invalid_request", "unsupported_platform"}
                reason = envelope.get("reason")
                return fallback(reason if isinstance(reason, str) and reason in allowed else "worker_failed")
            result = parse_proposal(envelope.get("response"), normalized, self.minimum_confidence, self.max_calls)
            result["timings"]["total_ms"] = round((time.monotonic() - started) * 1000, 3)
            worker_timings = envelope.get("timings", {})
            if isinstance(worker_timings, dict):
                for key in ("load_ms", "inference_ms"):
                    value = worker_timings.get(key)
                    if finite_number(value) and 0 <= value <= 60000:
                        result["timings"][key] = value
            return result
        except asyncio.CancelledError:
            cancelled.set()
            # A second caller cancellation must not release the router lock
            # while the first native process is still being stopped.
            while worker_task is not None and not worker_task.done():
                try:
                    await asyncio.shield(worker_task)
                except asyncio.CancelledError:
                    continue
                except NeedleError:
                    break
            raise
        except NeedleError as exc:
            return fallback(str(exc))
        except (OSError, RuntimeError):
            return fallback("worker_unavailable")
        finally:
            cancelled.set()
            self._busy.release()
