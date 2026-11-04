"""Policy/transport regressions. Real model checks are a separate explicit script."""
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from sight_core import needle


TOOLS = [{"type": "function", "function": {
    "name": "app.launch", "description": "Propose opening an allowed application for owner review.",
    "parameters": {"type": "object", "properties": {"application": {"type": "string", "enum": ["notepad", "calculator"]}},
                   "required": ["application"], "additionalProperties": False},
}}]


def response(**changes):
    return {"success": True, "confidence": 0.9,
            "function_calls": [{"name": "app.launch", "arguments": {"application": "notepad"}}], **changes}


def parse(raw, **kwargs):
    return needle.parse_proposal(raw, needle.normalize_tools(TOOLS), **kwargs)


def test_valid_call_is_only_a_proposal():
    result = parse(response())
    assert result["status"] == "proposed"
    assert result["reason"] == "requires_policy_review"
    assert result["calls"] == [{"name": "app.launch", "arguments": {"application": "notepad"}}]


@pytest.mark.parametrize("confidence", [None, True, False, "0.99", -1, 1.1, float("nan"), float("inf"), 10**1000])
def test_invalid_confidence_never_authorizes(confidence):
    assert parse(response(confidence=confidence))["reason"] == "unknown_confidence"


def test_low_confidence_and_withheld_calls_fall_back():
    assert parse(response(confidence=0.69))["reason"] == "low_confidence"
    assert parse(response(function_calls=[], suppressed_calls=response()["function_calls"]))["reason"] == "no_supported_call"
    assert parse(response(validation={"ungrounded": ["application"]}))["reason"] == "ungrounded_arguments"
    assert parse(response(error="secret must not be echoed"))["reason"] == "model_error"


@pytest.mark.parametrize("calls,reason", [
    ([{"name": "shell", "arguments": {"command": "calc"}}], "unknown_tool"),
    ([{"name": "app.launch", "arguments": {"application": "chrome"}}], "invalid_arguments"),
    ([{"name": "app.launch", "arguments": {"application": "notepad", "confirmed": True}}], "invalid_arguments"),
    ([{"name": "app.launch", "arguments": {}}], "invalid_arguments"),
    ([{"name": "app.launch", "arguments": '{"application":"notepad"}'}], "invalid_arguments"),
    ([{"name": "app.launch", "arguments": {"application": "notepad"}, "confirmed": True}], "invalid_call"),
    (response()["function_calls"] * 2, "call_budget_exceeded"),
])
def test_unknown_invalid_or_excess_calls_fail_closed(calls, reason):
    result = parse(response(function_calls=calls))
    assert result["reason"] == reason and result["calls"] == []


def test_duplicate_calls_rejected_even_with_larger_budget():
    assert parse(response(function_calls=response()["function_calls"] * 2), max_calls=2)["reason"] == "duplicate_call"


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"confidence":NaN}', '{"confidence":Infinity}', '{'])
def test_strict_json_rejects_ambiguous_or_nonfinite_data(raw):
    with pytest.raises(needle.NeedleError):
        needle.strict_json(raw)


def test_schema_and_argument_limits():
    schema = {"type": "object", "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 3}},
              "required": ["count"], "additionalProperties": False}
    for bad in [True, 0, 4, 1.0, float("inf")]:
        with pytest.raises(needle.NeedleError):
            needle.validate_arguments({"count": bad}, schema)
    needle.validate_arguments({"count": 2}, schema)
    for bad in [{"type": "object", "$ref": "https://invalid.example/schema"},
                {"type": "object", "additionalProperties": True},
                {"type": "string"}]:
        with pytest.raises(needle.NeedleError):
            needle.normalize_tools([{"name": "unsafe", "parameters": bad}])
    with pytest.raises(needle.NeedleError):
        needle.normalize_tools(TOOLS * 2)


def test_bel_selection_filters_unsupported_schema_without_poisoning_eligible_tools(tmp_path):
    from sight_core.bel import Bel
    from sight_core.capabilities import Capabilities
    from sight_core.store import Store
    from sight_core.tools import LocalFiles
    store = Store(tmp_path)
    files = LocalFiles(tmp_path / 'files')
    bel = Bel(store, files, Capabilities(store, files))
    selected = bel.select('Open Notepad')
    assert [tool.name for tool in selected] == ['app.launch']
    # The similarly named in-app reminder has a nullable schema that this
    # compact adapter cannot support. It must not disable application proposals.
    assert needle.normalize_tools([{'name': tool.name, 'description': tool.description,
                                   'parameters': tool.schema.model_json_schema()} for tool in selected])
    assert [tool.name for tool in bel.select('List files in my private workspace')] == ['files.list']
    assert 'files.create' in {tool.name for tool in bel.select('Create a file named greeting.txt containing Hello')}


def fake_assets(tmp_path, monkeypatch):
    assets = {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in {
        "needle3.cact": b"test model", "libneedle3.dll": b"never execute", "LICENSE": b"test license",
    }.items()}
    monkeypatch.setattr(needle, "ASSETS", assets)
    for name, data in {"needle3.cact": b"test model", "libneedle3.dll": b"never execute", "LICENSE": b"test license"}.items():
        (tmp_path / name).write_bytes(data)
    (tmp_path / "manifest.json").write_text(json.dumps(needle.expected_manifest()))
    return tmp_path


def test_assets_require_pinned_manifest_and_all_content(tmp_path, monkeypatch):
    root = fake_assets(tmp_path, monkeypatch)
    assert needle.verify_assets(root)["license"] == "Apache-2.0"
    (root / "libneedle3.dll").write_bytes(b"modified DLL!")
    with pytest.raises(needle.NeedleError, match="asset_integrity_failed"):
        needle.verify_assets(root)


def test_manifest_cannot_select_an_unpinned_asset(tmp_path, monkeypatch):
    root = fake_assets(tmp_path, monkeypatch)
    manifest = needle.expected_manifest()
    manifest["files"]["libneedle3.dll"]["sha256"] = "f" * 64
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(needle.NeedleError, match="asset_manifest_mismatch"):
        needle.verify_assets(root)


def test_missing_assets_are_offline_failure(tmp_path):
    with pytest.raises(needle.NeedleError, match="assets_unavailable"):
        needle.verify_assets(tmp_path)


@pytest.mark.skipif(needle.os.name != "nt", reason="Real Windows file-sharing lock")
def test_native_library_cannot_change_between_verification_and_load(tmp_path):
    from sight_core.needle_worker import locked_library
    dll = tmp_path / "libneedle3.dll"
    dll.write_bytes(b"synthetic asset; no native code loaded")
    replacement = tmp_path / "replacement.dll"
    replacement.write_bytes(b"substitution")
    before = dll.read_bytes()
    with locked_library(dll, needle):
        assert dll.read_bytes() == before
        with pytest.raises(PermissionError):
            dll.write_bytes(b"modified")
        with pytest.raises(PermissionError):
            replacement.replace(dll)
    assert dll.read_bytes() == before
    dll.write_bytes(b"lock released")


def test_worker_command_is_fixed_and_frozen_aware(tmp_path, monkeypatch):
    command = needle.worker_command(tmp_path)
    assert command[:3] == [sys.executable, "-I", "-S"]
    assert command[-2:] == ["--assets", str(tmp_path)]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    executable = tmp_path / "BEL.exe"
    executable.write_bytes(b"test placeholder, never executed")
    worker = tmp_path / "BEL-worker.exe"
    worker.write_bytes(b"test placeholder, never executed")
    monkeypatch.setattr(sys, "executable", str(executable))
    assert needle.worker_command(tmp_path) == [str(worker), "--worker", "needle", "--assets", str(tmp_path)]


def test_worker_deadline_stops_process():
    start = time.monotonic()
    with pytest.raises(needle.NeedleError, match="deadline_exceeded"):
        needle._run_worker([sys.executable, "-I", "-S", "-c", "import time; time.sleep(60)"], b"{}",
                           time.monotonic() + 0.2, threading.Event())
    assert time.monotonic() - start < 4


def test_worker_cancellation_stops_process():
    event = threading.Event()
    event.set()
    with pytest.raises(needle.NeedleError, match="cancelled"):
        needle._run_worker([sys.executable, "-I", "-S", "-c", "import time; time.sleep(60)"], b"{}",
                           time.monotonic() + 30, event)


def test_worker_output_is_bounded():
    with pytest.raises(needle.NeedleError, match="worker_output_overflow"):
        needle._run_worker([sys.executable, "-I", "-S", "-c", "print('a'*100000)"], b"{}",
                           time.monotonic() + 5, threading.Event())


def test_worker_environment_disables_network_telemetry_and_secret_inheritance(monkeypatch):
    monkeypatch.setenv("BEL_TEST_SECRET", "private-never-inherit")
    code = "import json,os; print(json.dumps({k:os.environ.get(k) for k in ['NEEDLE_TELEMETRY','DO_NOT_TRACK','HF_HUB_OFFLINE','BEL_TEST_SECRET']}))"
    raw = needle._run_worker([sys.executable, "-I", "-S", "-c", code], b"{}",
                             time.monotonic() + 5, threading.Event())
    assert json.loads(raw) == {"NEEDLE_TELEMETRY": "0", "DO_NOT_TRACK": "1", "HF_HUB_OFFLINE": "1", "BEL_TEST_SECRET": None}


def test_invalid_input_does_not_start_worker(monkeypatch):
    def forbidden(*args):
        pytest.fail("Invalid requests must not start a worker")
    monkeypatch.setattr(needle, "_run_worker", forbidden)
    router = needle.NeedleRouter()
    assert asyncio.run(router.propose("x" * 4097, TOOLS))["reason"] == "input_overflow_or_invalid"
    assert asyncio.run(router.propose("hello\0", TOOLS))["reason"] == "input_overflow_or_invalid"
    assert asyncio.run(router.propose("hello", []))["reason"] == "unsupported_tools"


@pytest.mark.parametrize("kwargs", [{"minimum_confidence": True}, {"minimum_confidence": 0},
                                    {"timeout_seconds": float("nan")}, {"timeout_seconds": 61}, {"max_calls": True}])
def test_router_configuration_is_bounded(kwargs):
    with pytest.raises(ValueError):
        needle.NeedleRouter(**kwargs)


def test_async_proposal_and_concurrent_rejection(monkeypatch):
    if needle.os.name != "nt":
        pytest.skip("Transport contract exercises Windows adapter")
    entered, release = threading.Event(), threading.Event()
    def worker(command, payload, deadline, cancelled):
        entered.set()
        release.wait(2)
        request = json.loads(payload)
        assert request["text"] == "Open notepad"
        return json.dumps({"ok": True, "response": response(), "timings": {"load_ms": 12}}).encode()
    monkeypatch.setattr(needle, "_run_worker", worker)
    async def run():
        router = needle.NeedleRouter()
        first = asyncio.create_task(router.propose("Open notepad", TOOLS))
        await asyncio.to_thread(entered.wait, 2)
        assert (await router.propose("Open calculator", TOOLS))["reason"] == "router_busy"
        release.set()
        result = await first
        assert result["status"] == "proposed" and result["timings"]["load_ms"] == 12
    asyncio.run(run())


def test_async_cancellation_finishes_worker_before_releasing_router(monkeypatch):
    if needle.os.name != "nt":
        pytest.skip("Transport contract exercises Windows adapter")
    entered, stopped = threading.Event(), threading.Event()
    def worker(command, payload, deadline, cancelled):
        entered.set()
        assert cancelled.wait(3)
        stopped.set()
        raise needle.NeedleError("cancelled")
    monkeypatch.setattr(needle, "_run_worker", worker)
    async def run():
        router = needle.NeedleRouter()
        task = asyncio.create_task(router.propose("Open notepad", TOOLS))
        await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set() and not router._busy.locked()
    asyncio.run(run())


def test_repeated_cancellation_keeps_router_busy_until_worker_stops(monkeypatch):
    if needle.os.name != "nt":
        pytest.skip("Transport contract exercises Windows adapter")
    entered, cancelling, release, stopped = (threading.Event() for _ in range(4))

    def worker(command, payload, deadline, cancelled):
        entered.set()
        assert cancelled.wait(3)
        cancelling.set()
        assert release.wait(3)
        stopped.set()
        raise needle.NeedleError("cancelled")

    monkeypatch.setattr(needle, "_run_worker", worker)

    async def run():
        router = needle.NeedleRouter()
        task = asyncio.create_task(router.propose("Open notepad", TOOLS))
        await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.to_thread(cancelling.wait, 2)
        task.cancel()
        await asyncio.sleep(.03)
        try:
            assert router._busy.locked(), "A repeated cancel must not permit a second native worker"
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.to_thread(stopped.wait, 2)
        await asyncio.sleep(.03)
        assert stopped.is_set() and not router._busy.locked()

    asyncio.run(run())


@pytest.mark.parametrize("payload", [{"ok": False, "reason": []}, {"ok": True, "response": response(), "timings": []}])
def test_malformed_worker_metadata_does_not_crash_router(monkeypatch, payload):
    if needle.os.name != "nt":
        pytest.skip("Transport contract exercises Windows adapter")
    monkeypatch.setattr(needle, "_run_worker", lambda *args: json.dumps(payload).encode())
    result = asyncio.run(needle.NeedleRouter().propose("Open notepad", TOOLS))
    assert result["status"] in {"proposed", "fallback"}
