"""Unit and Integration Tests for Stage 10 BEL V1 Convergence & Finalisation."""
from __future__ import annotations

import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from sight_core.api import create_app
from sight_core.config import Config
from sight_core.tray_service import TrayService
from sight_core.rsi.boundaries import PROTECTED_CORE_FILES
from scripts.run_golden_suite import verify_axiom_1_integrity, verify_convergence_subsystems

URL = "http://127.0.0.1:8080"


def authenticate(client, app):
    client.post(
        "/api/session/claim",
        json={"token": app.state.bootstrap_token},
        headers={"origin": URL},
    ).raise_for_status()
    client.headers["x-sight-csrf"] = client.get("/api/session").json()["csrf"]


@pytest.fixture
def api_client(tmp_path):
    app = create_app(Config(tmp_path / "data", local_tts=False))
    with TestClient(app, base_url=URL) as client:
        authenticate(client, app)
        yield app, client


def test_tray_service_lifecycle():
    summon_called = False

    def on_summon():
        nonlocal summon_called
        summon_called = True

    tray = TrayService(backend_url=URL, on_open_ui=on_summon)
    assert not tray.is_running
    assert not tray.serious_mode

    # Toggle Serious Mode
    res = tray.toggle_serious_mode()
    assert res is True
    assert tray.serious_mode is True

    # Hotkey trigger
    tray.trigger_hotkey_summon()
    assert summon_called is True

    # Start and Stop
    tray.start(non_blocking=True)
    assert tray.is_running is True
    status = tray.get_status()
    assert status.is_running is True
    assert status.serious_mode is True

    tray.stop()
    assert tray.is_running is False


def test_stage10_api_endpoints(api_client):
    app, client = api_client

    # 1. Tray Status
    res_st = client.get("/api/system/tray/status")
    assert res_st.status_code == 200
    data = res_st.json()
    assert "is_running" in data
    assert data["registered_hotkey"] == "Win+Shift+B"

    # 2. Tray Summon
    res_sm = client.post("/api/system/tray/summon", json={})
    assert res_sm.status_code == 200
    assert res_sm.json()["summoned"] is True

    # 3. Tray Serious Mode
    res_smode = client.post("/api/system/tray/serious_mode", json={})
    assert res_smode.status_code == 200
    assert res_smode.json()["serious_mode"] is True

    # 4. Convergence Status
    res_conv = client.get("/api/system/convergence/status")
    assert res_conv.status_code == 200
    conv_data = res_conv.json()
    assert conv_data["version"] == "1.0.0"
    assert len(conv_data["stages_converged"]) == 10
    assert conv_data["axiom_1_compliant"] is True
    assert conv_data["status"] == "ready"


def test_axiom_1_boundary_integrity():
    workspace_root = Path(__file__).resolve().parents[1]
    res = verify_axiom_1_integrity(workspace_root)
    assert res["passed"] is True
    assert res["protected_files_audited"] == len(PROTECTED_CORE_FILES)
    assert len(res["missing_files"]) == 0


def test_subsystem_convergence_integrity():
    status = verify_convergence_subsystems()
    assert len(status) >= 25
    assert all(status.values())
