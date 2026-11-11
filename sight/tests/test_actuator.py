import pytest

from sight_core.actuator import (
    DesktopActuator,
    ActuatorActionType,
    BLACKLISTED_HOTKEYS,
)
from sight_core.vision import VisionService


def test_actuator_propose_and_execute_mouse_click():
    actuator = DesktopActuator()
    proposal = actuator.propose(
        action_type=ActuatorActionType.MOUSE_CLICK,
        arguments={"x": 50, "y": 50, "button": "left"},
        summary="Click at (50, 50)",
    )
    assert proposal.approval_id.startswith("act_")
    assert proposal.action_type == ActuatorActionType.MOUSE_CLICK
    assert not proposal.confirmed

    # Execute approved action
    result = actuator.execute_approved(proposal.approval_id)
    assert result["ok"] is True
    assert result["action"] == "mouse_click"


def test_blacklisted_hotkeys():
    actuator = DesktopActuator()
    for hotkey in ["Ctrl+Alt+Del", "ctrl+alt+delete", "win+l", "alt+f4"]:
        proposal = actuator.propose(
            action_type=ActuatorActionType.KEY_PRESS,
            arguments={"key": hotkey},
            summary=f"Press {hotkey}",
        )
        with pytest.raises(ValueError, match="blacklisted"):
            actuator.execute_approved(proposal.approval_id)


def test_invalid_or_replayed_approval_token():
    actuator = DesktopActuator()
    proposal = actuator.propose(
        action_type=ActuatorActionType.TYPE_TEXT,
        arguments={"text": "Hello BEL"},
        summary="Type text",
    )
    # Execute once
    actuator.execute_approved(proposal.approval_id)

    # Replay should fail
    with pytest.raises(ValueError, match="Invalid or already consumed"):
        actuator.execute_approved(proposal.approval_id)

    # Fake token should fail
    with pytest.raises(ValueError, match="Invalid or already consumed"):
        actuator.execute_approved("act_fake_nonce")


def test_out_of_bounds_click():
    actuator = DesktopActuator()
    proposal = actuator.propose(
        action_type=ActuatorActionType.MOUSE_CLICK,
        arguments={"x": 999999, "y": 999999, "button": "left"},
        summary="Out of bounds click",
    )
    with pytest.raises(ValueError, match="out of screen bounds"):
        actuator.execute_approved(proposal.approval_id)


def test_actuator_scroll_and_drag():
    actuator = DesktopActuator()
    # Scroll
    scroll_prop = actuator.propose(
        action_type=ActuatorActionType.MOUSE_SCROLL,
        arguments={"clicks": -3, "x": 100, "y": 100},
        summary="Scroll down",
    )
    scroll_res = actuator.execute_approved(scroll_prop.approval_id)
    assert scroll_res["ok"] is True
    assert scroll_res["action"] == "mouse_scroll"
    assert scroll_res["clicks"] == -3

    # Drag
    drag_prop = actuator.propose(
        action_type=ActuatorActionType.MOUSE_DRAG,
        arguments={"start_x": 50, "start_y": 50, "end_x": 150, "end_y": 150},
        summary="Drag element",
    )
    drag_res = actuator.execute_approved(drag_prop.approval_id)
    assert drag_res["ok"] is True
    assert drag_res["action"] == "mouse_drag"


def test_actuator_window_state():
    actuator = DesktopActuator()
    import os
    if os.name == "nt":
        import ctypes
        real_hwnd = ctypes.windll.user32.GetDesktopWindow()
    else:
        real_hwnd = 1234
    prop = actuator.propose(
        action_type=ActuatorActionType.WINDOW_STATE,
        arguments={"hwnd": real_hwnd, "state": "restore"},
        summary="Restore window",
    )
    res = actuator.execute_approved(prop.approval_id)
    assert res["ok"] is True
    assert res["action"] == "window_state"
    assert res["state"] == "restore"


def test_actuator_with_visual_verification(monkeypatch):
    from PIL import Image
    import io

    def fake_capture(*args, **kwargs):
        buf = io.BytesIO()
        Image.new("RGB", (200, 200), color=(100, 100, 100)).save(buf, format="PNG")
        return buf.getvalue()

    actuator = DesktopActuator()
    monkeypatch.setattr(actuator.vision_service, "capture", fake_capture)

    prop = actuator.propose(
        action_type=ActuatorActionType.TYPE_TEXT,
        arguments={"text": "Verified typing"},
        summary="Type with verification",
    )
    res = actuator.execute_approved(prop.approval_id, verify_visual=True)
    assert res["ok"] is True
    assert "visual_verification" in res
    assert not res["visual_verification"]["has_changed"]

