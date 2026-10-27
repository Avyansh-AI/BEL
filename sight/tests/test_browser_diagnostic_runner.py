"""Harness bookkeeping under simulated process-cleanup failures; no live browser."""
import json
from types import SimpleNamespace

import pytest

from scripts import browser_diagnostics as diagnostic


@pytest.mark.parametrize('cleanup', ['success', 'timeout', 'os_error'])
def test_timeout_evidence_precedes_cleanup_and_survives_its_failure(tmp_path, monkeypatch, cleanup):
    output = tmp_path / 'evidence.json'
    workers = []
    class Process:
        pid = 99999999
        returncode = None
        def __init__(self, *args, **kwargs):
            self.calls = 0
            workers.append(self)
        def communicate(self, timeout):
            self.calls += 1
            if self.calls == 1:
                raise diagnostic.subprocess.TimeoutExpired('synthetic worker', timeout)
            self.returncode = 1
            return '', ''

    def stop(*args, **kwargs):
        before = json.loads(output.read_text())
        assert before['attempts'][-1]['error_code'] == 'worker_timeout'
        assert before['attempts'][-1]['cleanup'] == 'pending'
        if cleanup == 'timeout':
            raise diagnostic.subprocess.TimeoutExpired('synthetic cleanup', 10)
        if cleanup == 'os_error':
            raise OSError('Synthetic cleanup failure')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(diagnostic.subprocess, 'Popen', Process)
    monkeypatch.setattr(diagnostic.subprocess, 'run', stop)
    monkeypatch.setattr(diagnostic.os, 'killpg', stop, raising=False)
    monkeypatch.setattr(diagnostic, 'memory', lambda: {'available': True, 'available_ram_mib': 512})
    assert diagnostic.run(output, rounds=1) == 1
    result = json.loads(output.read_text())
    assert result['complete'] is (cleanup == 'success')
    assert len(workers) == len(diagnostic.CASES) if cleanup == 'success' else len(workers) == 1
    assert all(row['error_code'] == 'worker_timeout' and not row['passed'] for row in result['attempts'])
    assert all(row['cleanup'] == ('completed' if cleanup == 'success' else 'unverified') for row in result['attempts'])
    if cleanup != 'success':
        assert result['aborted'] == 'owned_worker_cleanup_unverified'
