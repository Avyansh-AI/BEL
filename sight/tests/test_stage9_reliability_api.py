"""Integration tests for Stage 9 Reliability, Security & System Intelligence REST Endpoints."""
from __future__ import annotations

import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from sight_core.api import create_app
from sight_core.config import Config

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


def test_vault_endpoints(api_client):
    app, client = api_client

    # 1. Store secret
    res_store = client.post(
        "/api/security/vault/store",
        json={"key": "gemini_api_key", "value": "AIzaSyTestKey999"},
    )
    assert res_store.status_code == 200
    assert res_store.json()["stored"] is True

    # 2. List keys
    res_list = client.get("/api/security/vault/list")
    assert res_list.status_code == 200
    assert "gemini_api_key" in res_list.json()["keys"]

    # 3. Retrieve secret
    res_get = client.post(
        "/api/security/vault/retrieve",
        json={"key": "gemini_api_key"},
    )
    assert res_get.status_code == 200
    assert res_get.json()["value"] == "AIzaSyTestKey999"

    # 4. Status
    res_stat = client.get("/api/security/vault/status")
    assert res_stat.status_code == 200
    assert res_stat.json()["total_keys"] == 1

    # 5. Delete secret
    res_del = client.post(
        "/api/security/vault/delete",
        json={"key": "gemini_api_key"},
    )
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True


def test_watchdog_endpoints(api_client):
    app, client = api_client

    # 1. Heartbeat
    res_hb = client.post(
        "/api/system/watchdog/heartbeat",
        json={"source": "api_test"},
    )
    assert res_hb.status_code == 200
    assert res_hb.json()["heartbeat"] == "recorded"

    # 2. Status
    res_st = client.get("/api/system/watchdog/status")
    assert res_st.status_code == 200
    assert res_st.json()["healthy"] is True


def test_integrity_and_backup_endpoints(api_client, tmp_path):
    app, client = api_client

    # 1. Integrity verify with empty manifest
    res_int = client.post("/api/system/integrity/verify", json={"manifest": {}})
    assert res_int.status_code == 200
    assert res_int.json()["passed"] is True

    # 2. Create Backup
    backup_file = tmp_path / "manual_backup.enc"
    res_bak = client.post(
        "/api/system/backup/create",
        json={"output_path": str(backup_file)},
    )
    assert res_bak.status_code == 200
    assert res_bak.json()["success"] is True
    assert backup_file.exists()

    # 3. Restore Backup
    res_rest = client.post(
        "/api/system/backup/restore",
        json={"archive_path": str(backup_file)},
    )
    assert res_rest.status_code == 200
    assert res_rest.json()["success"] is True
