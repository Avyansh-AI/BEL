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
