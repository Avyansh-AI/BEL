import base64
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


def test_vision_status_endpoint(api_client):
    app, client = api_client
    res = client.get("/api/vision/status")
    assert res.status_code == 200
    data = res.json()
    assert data["enabled"] is True
    assert "resolution" in data


def test_vision_windows_endpoint(api_client):
    app, client = api_client
    res = client.get("/api/vision/windows")
    assert res.status_code == 200
    assert "windows" in res.json()
    assert isinstance(res.json()["windows"], list)


def test_vision_capture_endpoint_mocked(api_client, monkeypatch):
    app, client = api_client
    from PIL import Image
    def mock_grab(bbox=None):
        return Image.new("RGB", (640, 480), color=(100, 150, 200))
    monkeypatch.setattr("sight_core.vision.ImageGrab.grab", mock_grab)

    res = client.post("/api/vision/capture", json={"format": "jpeg", "quality": 80})
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert res.content[:2] == b"\xff\xd8"


def test_wake_process_and_status_endpoints(api_client):
    app, client = api_client
    status_res = client.get("/api/speech/wake/status")
    assert status_res.status_code == 200
    assert status_res.json()["state"] == "idle"

    # Process empty/silent chunk
    silent_b64 = base64.b64encode(b"\x00" * 3200).decode()
    proc_res = client.post("/api/speech/wake/process", json={"chunk": silent_b64, "simulate": False})
    assert proc_res.status_code == 200
    data = proc_res.json()
    assert not data["triggered"]
    assert not data["speech_detected"]

    # Process simulation trigger
    trig_res = client.post("/api/speech/wake/process", json={"chunk": silent_b64, "simulate": True})
    assert trig_res.status_code == 200
    assert trig_res.json()["triggered"] is True


def test_actuator_propose_and_execute_flow(api_client):
    app, client = api_client
    propose_res = client.post(
        "/api/actuator/propose",
        json={
            "action_type": "type_text",
            "arguments": {"text": "Verified Stage 5 Input"},
            "summary": "Type verification text",
        },
    )
    assert propose_res.status_code == 200
    proposal = propose_res.json()
    assert proposal["approval_id"].startswith("act_")
    assert not proposal["confirmed"]

    # Execute with the valid one-time token
    exec_res = client.post("/api/actuator/execute", json={"approval_id": proposal["approval_id"]})
    assert exec_res.status_code == 200
    assert exec_res.json()["ok"] is True
    assert exec_res.json()["action"] == "type_text"

    # Replay token fails with 400
    replay_res = client.post("/api/actuator/execute", json={"approval_id": proposal["approval_id"]})
    assert replay_res.status_code == 400
