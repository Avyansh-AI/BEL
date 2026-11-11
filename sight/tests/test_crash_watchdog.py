"""Unit tests for Stage 9 Crash Watchdog and Supervisor."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
import pytest

from sight_core.crash_watchdog import CrashWatchdog


def test_watchdog_heartbeat_and_states():
    with tempfile.TemporaryDirectory() as tmp_dir:
        watchdog = CrashWatchdog(tmp_dir, heartbeat_timeout_sec=0.5)

        # Initially healthy
        watchdog.record_heartbeat()
        stat1 = watchdog.check_health()
        assert stat1.healthy is True
        assert stat1.state == "monitoring"

        # Wait for timeout
        time.sleep(0.6)
        stat2 = watchdog.check_health()
        assert stat2.healthy is False
        assert stat2.state in ("degraded", "crashed")

        # Record heartbeat recovers health
        watchdog.record_heartbeat()
        stat3 = watchdog.check_health()
        assert stat3.healthy is True
        assert stat3.state == "monitoring"


def test_watchdog_recovery_trigger_and_reports():
    with tempfile.TemporaryDirectory() as tmp_dir:
        watchdog = CrashWatchdog(tmp_dir)

        # Trigger recovery
        report = watchdog.trigger_recovery(reason="Simulated SIGTERM", last_task="task_42")
        assert report.recovered is True
        assert report.reason == "Simulated SIGTERM"
        assert watchdog.restart_count == 1

        # Check report log
        recent = watchdog.get_recent_crashes()
        assert len(recent) == 1
        assert recent[0].last_known_task == "task_42"
