import io
import os
from PIL import Image
import pytest

from sight_core.vision import (
    BoundingBox,
    CaptureOptions,
    VisionService,
    WindowBounds,
    SENSITIVE_TITLE_PATTERNS,
)


def test_bounding_box_calculations():
    bbox = BoundingBox(left=100, top=200, width=800, height=600)
    assert bbox.right == 900
    assert bbox.bottom == 800
    assert bbox.box_tuple == (100, 200, 900, 800)


def test_sensitive_title_patterns():
    vs = VisionService()
    assert vs.is_title_sensitive("Bitwarden - Password Manager")
    assert vs.is_title_sensitive("KeePass 2")
    assert vs.is_title_sensitive("New Tab - InPrivate - Microsoft Edge")
    assert vs.is_title_sensitive("Google Chrome (Incognito)")
    assert vs.is_title_sensitive("1Password - Unlock")
    assert not vs.is_title_sensitive("Notepad")
    assert not vs.is_title_sensitive("Calculator")
    assert not vs.is_title_sensitive("Project Sight - Visual Studio Code")


def test_screen_size_retrieval():
    vs = VisionService()
    w, h = vs.get_screen_size()
    assert w >= 640
    assert h >= 480


@pytest.mark.skipif(os.name != "nt", reason="Requires Windows OS")
def test_window_enumeration():
    vs = VisionService()
    windows = vs.list_windows()
    assert isinstance(windows, list)
    # Check window structure
    for win in windows:
        assert isinstance(win, WindowBounds)
        assert win.rect.width > 0
        assert win.rect.height > 0
        if win.is_sensitive:
            assert win.title == "[REDACTED_SENSITIVE_WINDOW]"


def test_screen_capture_jpeg(monkeypatch):
    vs = VisionService()
    # Provide synthetic image if real desktop session is locked
    def mock_grab(bbox=None):
        return Image.new("RGB", (1920, 1080), color=(50, 100, 150))
    monkeypatch.setattr("sight_core.vision.ImageGrab.grab", mock_grab)

    opts = CaptureOptions(format="jpeg", quality=75, max_dimension=800)
    img_bytes = vs.capture(opts)
    assert isinstance(img_bytes, bytes)
    assert len(img_bytes) > 500
    assert img_bytes[:2] == b"\xff\xd8"  # JPEG SOI marker

    with Image.open(io.BytesIO(img_bytes)) as img:
        assert img.format == "JPEG"
        assert img.width <= 800
        assert img.height <= 800


def test_screen_capture_png(monkeypatch):
    vs = VisionService()
    def mock_grab(bbox=None):
        return Image.new("RGB", (1200, 900), color=(30, 40, 50))
    monkeypatch.setattr("sight_core.vision.ImageGrab.grab", mock_grab)

    opts = CaptureOptions(format="png", max_dimension=600)
    img_bytes = vs.capture(opts)
    assert isinstance(img_bytes, bytes)
    assert len(img_bytes) > 500
    assert img_bytes[:4] == b"\x89PNG"  # PNG magic bytes


def test_real_screen_capture_graceful():
    vs = VisionService()
    opts = CaptureOptions(max_dimension=600)
    try:
        data = vs.capture(opts)
        assert len(data) > 0
    except Exception as exc:
        from sight_core.vision import VisionUnavailable
        assert isinstance(exc, VisionUnavailable)


def test_ground_point():
    vs = VisionService()
    w, h = vs.get_screen_size()
    # Test point inside screen
    win = vs.ground_point(w // 2, h // 2)
    # May be None or a window, but must not crash
    if win:
        assert isinstance(win, WindowBounds)


def test_vision_status():
    vs = VisionService()
    status = vs.status()
    assert status["enabled"] is True
    assert status["available"] is True
    assert "resolution" in status
    assert status["privacy_redaction_active"] is True
