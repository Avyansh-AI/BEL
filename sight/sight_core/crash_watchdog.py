"""Crash Watchdog and Supervisor Subsystem for BEL (Stage 9).

Monitors backend service heartbeat, detects unresponsive hangs or fatal
crashes, triggers automatic process recovery, and logs diagnostics.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("bel.crash_watchdog")


class WatchdogStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    healthy: bool = True
    last_heartbeat_epoch: float = 0.0
    seconds_since_heartbeat: float = 0.0
    restart_count: int = 0
    consecutive_failures: int = 0
    state: str = "monitoring"  # monitoring, degraded, recovering, crashed


class CrashReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    timestamp_utc: float
    reason: str
    last_known_task: str | None = None
    stack_trace: str | None = None
    recovered: bool = False


class CrashWatchdog:
    """Supervises the health and heartbeat of the BEL application runtime."""

    def __init__(
        self,
        watchdog_dir: Path | str,
        heartbeat_timeout_sec: float = 15.0,
        max_restarts_per_minute: int = 3,
    ) -> None:
        self.watchdog_dir = Path(watchdog_dir).resolve()
        self.watchdog_dir.mkdir(parents=True, exist_ok=True)
        self.crash_log_file = self.watchdog_dir / "crash_reports.jsonl"
        self.heartbeat_timeout_sec = heartbeat_timeout_sec
        self.max_restarts_per_minute = max_restarts_per_minute

        self.last_heartbeat: float = time.time()
        self.restart_count: int = 0
        self.consecutive_failures: int = 0
        self.recent_restart_epochs: list[float] = []

    def record_heartbeat(self, source: str = "fastapi_core") -> None:
        """Invoked by the backend loop or watchdog ping endpoint."""
        self.last_heartbeat = time.time()
        self.consecutive_failures = 0

    def check_health(self) -> WatchdogStatus:
        """Evaluate whether the runtime is responsive or hanging."""
        now = time.time()
        elapsed = now - self.last_heartbeat

        if elapsed > self.heartbeat_timeout_sec:
            self.consecutive_failures += 1
            state = "degraded" if self.consecutive_failures < 2 else "crashed"
            healthy = False
        else:
            state = "monitoring"
            healthy = True

        return WatchdogStatus(
            healthy=healthy,
            last_heartbeat_epoch=self.last_heartbeat,
            seconds_since_heartbeat=round(elapsed, 2),
            restart_count=self.restart_count,
            consecutive_failures=self.consecutive_failures,
            state=state,
        )

    def trigger_recovery(self, reason: str, last_task: str | None = None, stack_trace: str | None = None) -> CrashReport:
        """Log crash diagnostic and increment recovery counters."""
        now = time.time()
        self.recent_restart_epochs = [t for t in self.recent_restart_epochs if now - t < 60.0]

        if len(self.recent_restart_epochs) >= self.max_restarts_per_minute:
            logger.critical("Crash loop threshold reached (%d restarts in 60s). Pausing.", len(self.recent_restart_epochs))
            recovered = False
        else:
            self.recent_restart_epochs.append(now)
            self.restart_count += 1
            self.last_heartbeat = now
            self.consecutive_failures = 0
            recovered = True

        report = CrashReport(
            timestamp_utc=now,
            reason=reason,
            last_known_task=last_task,
            stack_trace=stack_trace,
            recovered=recovered,
        )

        # Append to crash log
        with open(self.crash_log_file, "a", encoding="utf-8") as f:
            f.write(report.model_dump_json() + "\n")

        return report

    def get_recent_crashes(self, max_reports: int = 20) -> list[CrashReport]:
        """Read recent crash reports from disk."""
        if not self.crash_log_file.exists():
            return []
        reports: list[CrashReport] = []
        try:
            with open(self.crash_log_file, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        reports.append(CrashReport.model_validate_json(stripped))
        except Exception:
            pass
        return reports[-max_reports:]
