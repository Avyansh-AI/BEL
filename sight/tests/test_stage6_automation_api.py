import base64
import io
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest

from sight_core.api import create_app
from sight_core.config import Config
from sight_core.ui_grounding import UIControl, UIControlType
from sight_core.vision import BoundingBox

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


def make_b64_image(color=(255, 255, 255), add_rect=None) -> str:
    img = Image.new("RGB", (200, 200), color=color)
    if add_rect:
        draw = ImageDraw.Draw(img)
        draw.rectangle(add_rect, fill=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_action_verify_endpoint(api_client):
    app, client = api_client
    pre_b64 = make_b64_image(color=(255, 255, 255))
    # Identical comparison
    res = client.post(
        "/api/automation/action/verify",
        json={"pre_image": pre_b64, "post_image": pre_b64},
    )
    assert res.status_code == 200
    data = res.json()
    assert not data["has_changed"]
    assert data["changed_pixels"] == 0

    # Image with visual change
    post_b64 = make_b64_image(color=(255, 255, 255), add_rect=(20, 20, 80, 80))
    res2 = client.post(
        "/api/automation/action/verify",
        json={"pre_image": pre_b64, "post_image": post_b64},
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["has_changed"] is True
    assert data2["changed_pixels"] > 500
    assert data2["bounding_box"] is not None


def test_ui_controls_and_ground_endpoints(api_client):
    app, client = api_client
    # Mock UI Grounding service controls
    mock_ctrl = UIControl(
        hwnd=999,
        class_name="Button",
        control_type=UIControlType.BUTTON,
        text="Click Me",
        bounding_box=BoundingBox(left=100, top=100, width=80, height=30),
        is_enabled=True,
        is_visible=True,
    )
    app.state.ui_grounding.enumerate_controls = lambda parent_hwnd=None: [mock_ctrl]

    # Test /api/automation/ui/controls
    ctrls_res = client.post("/api/automation/ui/controls", json={})
    assert ctrls_res.status_code == 200
    ctrls_data = ctrls_res.json()["controls"]
    assert len(ctrls_data) == 1
    assert ctrls_data[0]["text"] == "Click Me"
    assert ctrls_data[0]["control_type"] == "button"

    # Test /api/automation/ui/ground (inside button)
    ground_res = client.post("/api/automation/ui/ground", json={"x": 120, "y": 110})
    assert ground_res.status_code == 200
    assert ground_res.json()["found"] is True
    assert ground_res.json()["control"]["hwnd"] == 999

    # Test /api/automation/ui/ground (outside button)
    ground_miss = client.post("/api/automation/ui/ground", json={"x": 10, "y": 10})
    assert ground_miss.status_code == 200
    assert ground_miss.json()["found"] is False


def test_browser_security_rejection_endpoints(api_client):
    app, client = api_client
    # Navigation to prohibited schemes
    bad_res = client.post("/api/automation/browser/navigate", json={"url": "file:///C:/test.txt"})
    assert bad_res.status_code == 403
    assert "prohibited" in bad_res.json()["error"]

    # Navigation to restricted localhost without permission
    local_res = client.post("/api/automation/browser/navigate", json={"url": "http://127.0.0.1:8080/evil"})
    assert local_res.status_code == 403
    assert "restricted" in local_res.json()["error"]
