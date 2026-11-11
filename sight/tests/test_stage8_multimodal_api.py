"""Integration tests for Stage 8 Multimodal & Proactive REST Endpoints."""
from __future__ import annotations

import base64
import io
import time
from fastapi.testclient import TestClient
from PIL import Image
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


def make_b64_image(width=100, height=100, color=(120, 160, 200)) -> str:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_vlm_endpoints(api_client):
    app, client = api_client
    b64_img = make_b64_image()

    # 1. Query
    res_q = client.post(
        "/api/multimodal/vlm/query",
        json={"prompt": "Describe this visual", "image_base64": b64_img},
    )
    assert res_q.status_code == 200
    assert "visual_metadata" in res_q.json()

    # 2. Chart
    res_chart = client.post(
        "/api/multimodal/vlm/chart",
        json={"image_base64": b64_img},
    )
    assert res_chart.status_code == 200
    assert "data_points" in res_chart.json()

    # 3. Wireframe
    res_wf = client.post(
        "/api/multimodal/vlm/wireframe",
        json={"image_base64": b64_img},
    )
    assert res_wf.status_code == 200
    assert len(res_wf.json()["elements"]) >= 1


def test_document_parse_endpoint(api_client):
    app, client = api_client
    md_content = """# Roadmap Phase
Key deliverables include multimodal integration.

| Phase | Status |
| --- | --- |
| Stage 8 | Active |
"""
    res = client.post(
        "/api/multimodal/document/parse",
        json={"content": md_content, "format": "markdown"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["file_type"] == "markdown"
    assert len(data["sections"]) >= 1
    assert len(data["tables"]) == 1


def test_acoustic_endpoints(api_client):
    app, client = api_client
    # Silent PCM (16000 samples = 1s, 32000 bytes)
    silent_pcm = b"\x00\x00" * 8000
    b64_audio = base64.b64encode(silent_pcm).decode("ascii")

    # 1. Classify
    res_class = client.post(
        "/api/multimodal/audio/classify",
        json={"audio_base64": b64_audio, "sample_rate": 16000},
    )
    assert res_class.status_code == 200
    assert res_class.json()["scene_type"] == "silence"

    # 2. Summarize
    transcript = """
    Agenda: Stage 8 verification.
    Decision: All acceptance tests pass.
    Alice will sign off on the release.
    """
    res_sum = client.post(
        "/api/multimodal/audio/summarize",
        json={"transcript": transcript},
    )
    assert res_sum.status_code == 200
    data = res_sum.json()
    assert len(data["action_items"]) >= 1
    assert data["action_items"][0]["owner"] == "Alice"


def test_proactive_endpoints(api_client):
    app, client = api_client

    # 1. Briefing
    res_b = client.post(
        "/api/proactive/briefing",
        json={"briefing_type": "morning", "owner_name": "Tony"},
    )
    assert res_b.status_code == 200
    assert "Good morning, Tony" in res_b.json()["spoken_summary"]

    # 2. Reminder
    res_r = client.post(
        "/api/proactive/reminders",
        json={"title": "Review Multi-Modal Log", "due_epoch": time.time() + 7200},
    )
    assert res_r.status_code == 200
    assert res_r.json()["created"] is True

    # 3. Health check
    res_h = client.post(
        "/api/proactive/health_check",
        json={},
    )
    assert res_h.status_code == 200
    assert "clean_git_tree" in res_h.json()
