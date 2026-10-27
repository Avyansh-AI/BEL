"""Failure-protocol regressions using real, isolated synthetic child processes.

These exercise parent/worker transport and redaction, not Chromium's compositor.
The IPC cases use no browser. Final classification cases launch real Chromium
with injected capture failures; no speech, remote endpoint or owner data is used.
"""
import asyncio
import json

import pytest

from sight_core import capabilities


CANARY = "SYNTHETIC_PRIVATE_HTML_AND_FIELD_CANARY"
CAPTURE_CODE = "browser_capture_unavailable"
GENERIC_MESSAGE = "Adapter dependency unavailable or operation failed"
RESOURCES = {
    "total_ram_mib": 8192,
    "available_ram_mib": 1234,
    "available_commit_mib": 5678,
}


@pytest.fixture
def child_worker(tmp_path, monkeypatch, app):
    """Replace only the child executable source, preserving actual IPC and exit."""
    root = tmp_path / "synthetic-worker"
    source = root / "sight_core" / "capability_worker.py"
    source.parent.mkdir(parents=True)
    calls = root / "calls.txt"
    monkeypatch.setattr(capabilities, "ROOT", root)

    def install(payload=None, *, raw=None, returncode=1):
        output = json.dumps(payload) if raw is None else raw
        source.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "sys.stdin.buffer.read()\n"
            f"with Path({str(calls)!r}).open('a', encoding='utf-8') as stream:\n"
            "    stream.write('called\\n')\n"
            f"sys.stdout.write({output!r})\n"
            f"sys.exit({returncode})\n",
            encoding="utf-8",
        )
        return calls

    return install


def failure(code=CAPTURE_CODE, stage="screenshot", resources=None):
    return {
        "error": "Adapter failed",
        "code": code,
        "diagnostics": {
            "stage": stage,
            "resources": RESOURCES if resources is None else resources,
            "raw_exception": CANARY,
            "html": CANARY,
            "fields": {"owner": CANARY},
        },
        "raw_exception": CANARY,
        "html": CANARY,
    }


def worker_error(app, identifier="browser.inspect"):
    with pytest.raises(ValueError) as caught:
        asyncio.run(app.state.capabilities.worker(identifier, {}))
    assert CANARY not in str(caught.value)
    assert CANARY not in repr(vars(caught.value))
    return caught.value


@pytest.mark.parametrize(
    "code,stage",
    [
        (CAPTURE_CODE, "screenshot"),
        ("browser_timeout", "content"),
        ("browser_closed", "page"),
        ("browser_failed", "cleanup"),
    ],
)
def test_real_child_failure_preserves_only_safe_diagnostics(
    child_worker, app, code, stage
):
    calls = child_worker(failure(code, stage))
    error = worker_error(app)
    assert getattr(error, "code", None) == code
    assert getattr(error, "diagnostics", None) == {
        "stage": stage,
        "resources": RESOURCES,
    }
    assert calls.read_text(encoding="utf-8") == "called\n"
    assert app.state.capabilities.artifacts.list() == []


@pytest.mark.parametrize("stage", ["launch", "context", "fields", "cleanup"])
def test_safe_worker_stages_survive_transport(child_worker, app, stage):
    child_worker(failure(stage=stage))
    assert getattr(worker_error(app), "diagnostics", None) == {
        "stage": stage,
        "resources": RESOURCES,
    }


@pytest.mark.parametrize("stage", [CANARY, None, ["screenshot"], {"raw": CANARY}])
def test_untrusted_stage_is_replaced_with_fixed_unknown(child_worker, app, stage):
    child_worker(failure(stage=stage))
    assert getattr(worker_error(app), "diagnostics", None) == {
        "stage": "unknown",
        "resources": RESOURCES,
    }


@pytest.mark.parametrize("invalid", [True, False, -1, 2**40 + 1, 1.5, "123", None, {}])
def test_resource_values_reject_bool_negative_oversize_and_nonintegers(
    child_worker, app, invalid
):
    resources = RESOURCES | {
        "available_ram_mib": invalid,
        "owner_field": CANARY,
    }
    child_worker(failure(resources=resources))
    error = worker_error(app)
    assert getattr(error, "code", None) == CAPTURE_CODE
    assert getattr(error, "diagnostics", None) == {
        "stage": "screenshot",
        "resources": {"total_ram_mib": 8192, "available_commit_mib": 5678},
    }


def test_resource_integer_boundaries_are_retained(child_worker, app):
    resources = {"available_ram_mib": 0, "available_commit_mib": 2**40}
    child_worker(failure(resources=resources))
    assert getattr(worker_error(app), "diagnostics", None) == {
        "stage": "screenshot",
        "resources": resources,
    }


@pytest.mark.parametrize("code", [CANARY, None, [CAPTURE_CODE], {"code": CAPTURE_CODE}])
def test_unknown_or_unhashable_codes_fail_without_body_disclosure(
    child_worker, app, code
):
    child_worker(failure(code=code))
    error = worker_error(app)
    assert getattr(error, "code", None) == "adapter_failed"
    assert getattr(error, "diagnostics", None) == {}
    assert str(error) == GENERIC_MESSAGE


@pytest.mark.parametrize("raw", [CANARY, "null", "[]", '"' + CANARY + '"', "{"])
def test_malformed_worker_failure_uses_fixed_generic_error(child_worker, app, raw):
    child_worker(raw=raw)
    error = worker_error(app)
    assert getattr(error, "code", None) == "adapter_failed"
    assert getattr(error, "diagnostics", None) == {}
    assert str(error) == GENERIC_MESSAGE


def test_browser_diagnostics_cannot_be_spoofed_by_speech_worker(child_worker, app):
    child_worker(failure())
    error = worker_error(app, identifier="speech.render")
    assert getattr(error, "code", None) == "adapter_failed"
    assert getattr(error, "diagnostics", None) == {}
    assert str(error) == GENERIC_MESSAGE


def test_oversized_failure_body_cannot_bypass_output_limit(child_worker, app):
    payload = failure() | {"padding": "x" * (12 * 1024**2)}
    child_worker(payload)
    error = worker_error(app)
    assert getattr(error, "code", None) == "adapter_failed"
    assert getattr(error, "diagnostics", None) == {}
    assert str(error) == GENERIC_MESSAGE


def test_api_failure_records_safe_diagnostics_without_artifact_or_retry(
    child_worker, app, client
):
    calls = child_worker(failure())
    path = "/api/capability/invoke"
    args = {
        "id": "browser.inspect",
        "arguments": {"html": "<p>" + CANARY + "</p>", "fields": {}},
    }
    prepared = client.post("/api/actions/prepare", json={"path": path, "args": args})
    assert prepared.status_code == 200, prepared.text
    grant = prepared.json()
    body = grant["args"] | {"actionApproval": grant["approvalId"]}
    response = client.post(path, json=body)
    assert response.status_code == 409
    assert CANARY not in response.text
    assert "Nothing is automatically retried" in response.json()["error"]
    assert client.post(path, json=body).status_code == 403
    assert calls.read_text(encoding="utf-8") == "called\n"
    assert client.get("/api/capability/artifacts").json() == {"items": []}
    events = app.state.capabilities.store.events(100)
    failed = [row for row in events if row["type"] == "capability.failed"]
    assert len(failed) == 1
    assert failed[0]["payload"] == {
        "id": "browser.inspect",
        "code": CAPTURE_CODE,
        "diagnostics": {"stage": "screenshot", "resources": RESOURCES},
    }
    assert not any(row["type"] == "capability.finished" for row in events)
    assert CANARY not in json.dumps(events)


@pytest.mark.parametrize('fault', ['capture', 'timeout', 'closed', 'capture_and_cleanup'])
def test_browser_failure_classification_and_cleanup_with_real_process(monkeypatch, fault):
    """Inject a failure after actual page setup; this is not a compositor reproduction."""
    from playwright.sync_api import BrowserType, Browser, Page, Locator, Error, TimeoutError
    from sight_core import capability_worker as worker
    native = []
    calls = {'capture': 0, 'fill': 0}
    launch, capture, close, fill = BrowserType.launch, Page.screenshot, Browser.close, Locator.fill

    def track_launch(self, **kwargs):
        value = launch(self, **kwargs)
        native.append(value)
        return value

    def track_fill(self, *args, **kwargs):
        calls['fill'] += 1
        return fill(self, *args, **kwargs)

    def fail_capture(self, **kwargs):
        calls['capture'] += 1
        if fault == 'closed':
            self.close()
            return capture(self, **kwargs)
        if fault == 'timeout':
            raise TimeoutError('Synthetic timeout ' + CANARY)
        raise Error('Page.captureScreenshot: Unable to capture screenshot ' + CANARY)

    def fail_cleanup(self, **kwargs):
        close(self, **kwargs)
        raise Error('Synthetic cleanup error ' + CANARY)

    monkeypatch.setattr(BrowserType, 'launch', track_launch)
    monkeypatch.setattr(Locator, 'fill', track_fill)
    monkeypatch.setattr(Page, 'screenshot', fail_capture)
    monkeypatch.setattr(worker, 'memory_snapshot', lambda: RESOURCES)
    if fault == 'capture_and_cleanup':
        monkeypatch.setattr(Browser, 'close', fail_cleanup)
    with pytest.raises(worker.BrowserFailure) as caught:
        worker.browser({'html': '<p>' + CANARY + '</p><input id="name">', 'fields': {'name': CANARY}})
    expected = {'timeout': 'browser_timeout', 'closed': 'browser_closed'}.get(fault, CAPTURE_CODE)
    payload = worker.failure_payload(caught.value)
    assert payload == {'error': 'Adapter failed', 'code': expected,
                       'diagnostics': {'stage': 'screenshot', 'resources': RESOURCES}}
    assert CANARY not in json.dumps(payload)
    assert CANARY not in str(caught.value)
    assert calls == {'capture': 1, 'fill': 1}
    assert len(native) == 1 and not native[0].is_connected()


def test_unclassified_failure_payload_contains_no_exception_text():
    from sight_core.capability_worker import failure_payload
    assert failure_payload(ValueError(CANARY)) == {'error': 'Adapter failed', 'code': 'adapter_failed'}
