"""Unit tests for Stage 8 Proactive Executive Scheduler."""
from __future__ import annotations

import tempfile
import time
from pathlib import Path
import pytest

from sight_core.proactive import Proactive
from sight_core.proactive_scheduler import ProactiveScheduler
from sight_core.store import Store


def test_proactive_briefing_generation():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = Store(Path(tmp_dir))
        proactive = Proactive(store)
        scheduler = ProactiveScheduler(proactive, workspace_root=tmp_dir)

        # 1. Generate morning briefing
        morning = scheduler.generate_briefing(briefing_type="morning", owner_name="Commander")
        assert morning.briefing_type == "morning"
        assert "Good morning, Commander" in morning.spoken_summary
        assert morning.system_health_ok is True
        assert len(morning.items) >= 1

        # 2. Schedule contextual reminder
        future_time = time.time() + 3600
        rem_res = scheduler.schedule_contextual_reminder(
            title="Review Multimodal Test Baseline",
            due_epoch=future_time,
        )
        assert rem_res["created"] is True

        # 3. Generate evening debriefing
        evening = scheduler.generate_briefing(briefing_type="evening", owner_name="Commander")
        assert evening.briefing_type == "evening"
        assert "Good evening, Commander" in evening.spoken_summary
        # Should now reflect 1 pending reminder
        reminder_items = [i for i in evening.items if i.category == "reminder"]
        assert len(reminder_items) == 1
        assert "Review Multimodal Test Baseline" in reminder_items[0].title


def test_project_health_audit():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = Store(Path(tmp_dir))
        proactive = Proactive(store)
        scheduler = ProactiveScheduler(proactive, workspace_root=tmp_dir)

        # Create temporary file
        (Path(tmp_dir) / "corrupt.tmp").write_text("temporary data")

        report = scheduler.audit_project_health(tmp_dir)
        assert report.project_name == Path(tmp_dir).name
        assert any("temporary" in r.lower() for r in report.recommendations)
