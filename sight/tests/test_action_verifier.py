import io
from PIL import Image, ImageDraw
import pytest

from sight_core.action_verifier import ActionVerifier, VisualDelta
from sight_core.vision import BoundingBox


def make_test_image(color=(255, 255, 255), add_rect=None) -> bytes:
    img = Image.new("RGB", (400, 300), color=color)
    if add_rect:
        draw = ImageDraw.Draw(img)
        draw.rectangle(add_rect, fill=(200, 50, 50))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_action_verifier_identical_images():
    verifier = ActionVerifier(tolerance=10, min_change_pixels=20)
    img_bytes = make_test_image()
    delta = verifier.compare_images(img_bytes, img_bytes)
    assert not delta.has_changed
    assert delta.changed_pixels == 0
    assert delta.change_percentage == 0.0
    assert delta.bounding_box is None


def test_action_verifier_detects_visual_change():
    verifier = ActionVerifier(tolerance=10, min_change_pixels=50)
    pre = make_test_image(color=(255, 255, 255))
    # Add a 60x60 square
    post = make_test_image(color=(255, 255, 255), add_rect=(50, 50, 110, 110))

    delta = verifier.compare_images(pre, post)
    assert delta.has_changed
    assert delta.changed_pixels >= 3000
    assert delta.change_percentage > 2.0
    assert delta.bounding_box is not None
    assert delta.bounding_box.left == 50
    assert delta.bounding_box.top == 50


def test_action_verifier_roi_crop():
    verifier = ActionVerifier(tolerance=10, min_change_pixels=20)
    pre = make_test_image(color=(255, 255, 255))
    # Add change at (50, 50, 100, 100)
    post = make_test_image(color=(255, 255, 255), add_rect=(50, 50, 100, 100))

    # Compare outside ROI (e.g. 200, 200, 300, 300)
    outside_roi = BoundingBox(left=200, top=200, width=100, height=100)
    delta_outside = verifier.compare_images(pre, post, target_roi=outside_roi)
    assert not delta_outside.has_changed

    # Compare inside ROI (e.g. 40, 40, 120, 120)
    inside_roi = BoundingBox(left=40, top=40, width=80, height=80)
    delta_inside = verifier.compare_images(pre, post, target_roi=inside_roi)
    assert delta_inside.has_changed


def test_generate_diff_overlay():
    verifier = ActionVerifier()
    pre = make_test_image(color=(255, 255, 255))
    post = make_test_image(color=(255, 255, 255), add_rect=(30, 30, 80, 80))
    overlay_bytes = verifier.generate_diff_overlay(pre, post)
    assert isinstance(overlay_bytes, bytes)
    assert len(overlay_bytes) > 200
    assert overlay_bytes[:2] == b"\xff\xd8"  # JPEG SOI
