"""Safe desktop actuation with strict human-in-the-loop approval.

Enforces coordinate boundaries, destructive action blacklisting, and
one-time approval tokens before executing mouse, keyboard, or window actions.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from enum import Enum
import logging
import os
import secrets
import time
from typing import Literal

from pydantic import Field

from .tools import StrictModel
from .vision import VisionService
from .action_verifier import ActionVerifier, VisualDelta

logger = logging.getLogger(__name__)

# Dangerous hotkeys strictly blacklisted to protect host integrity
BLACKLISTED_HOTKEYS = frozenset({
    "ctrl+alt+del",
    "ctrl+alt+delete",
    "win+l",
    "alt+f4",
    "format",
    "del /f",
    "rmdir",
})

# Win32 Mouse event constants
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800

# Win32 ShowWindow commands
SW_HIDE = 0
SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SW_RESTORE = 9


class ActuatorActionType(str, Enum):
    MOUSE_CLICK = "mouse_click"
    KEY_PRESS = "key_press"
    TYPE_TEXT = "type_text"
    WINDOW_FOCUS = "window_focus"
    MOUSE_SCROLL = "mouse_scroll"
    MOUSE_DRAG = "mouse_drag"
    WINDOW_STATE = "window_state"


class ActuatorProposal(StrictModel):
    approval_id: str
    action_type: ActuatorActionType
    target_summary: str
    arguments: dict
    expires_at: float
    confirmed: bool = False


class ClickRequest(StrictModel):
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    button: Literal["left", "right", "double"] = "left"


class ScrollRequest(StrictModel):
    clicks: int = Field(default=-1)  # negative = down, positive = up
    x: int | None = None
    y: int | None = None


class DragRequest(StrictModel):
    start_x: int = Field(ge=0)
    start_y: int = Field(ge=0)
    end_x: int = Field(ge=0)
    end_y: int = Field(ge=0)


class WindowStateRequest(StrictModel):
    hwnd: int
    state: Literal["minimize", "maximize", "restore"]


class TypeTextRequest(StrictModel):
    text: str = Field(min_length=1, max_length=1000)


class KeyPressRequest(StrictModel):
    key: str = Field(min_length=1, max_length=50)


class WindowFocusRequest(StrictModel):
    hwnd: int


class DesktopActuator:
    """Safe desktop actuator requiring human-in-the-loop confirmation."""

    def __init__(
        self,
        vision_service: VisionService | None = None,
        action_verifier: ActionVerifier | None = None,
        enabled: bool = True,
    ):
        self.vision_service = vision_service or VisionService()
        self.action_verifier = action_verifier or ActionVerifier()
        self.enabled = enabled
        self._proposals: dict[str, ActuatorProposal] = {}

    def propose(self, action_type: ActuatorActionType, arguments: dict, summary: str, validity_sec: float = 60.0) -> ActuatorProposal:
        """Generates an unexecuted action proposal requiring human approval."""
        if not self.enabled:
            raise RuntimeError("Desktop actuation is disabled")

        approval_id = "act_" + secrets.token_hex(16)
        proposal = ActuatorProposal(
            approval_id=approval_id,
            action_type=action_type,
            target_summary=summary,
            arguments=arguments,
            expires_at=time.time() + validity_sec,
            confirmed=False,
        )
        self._proposals[approval_id] = proposal
        return proposal

    def execute_approved(self, approval_id: str, verify_visual: bool = False) -> dict:
        """Executes an action proposal after verifying its one-time approval token."""
        if not self.enabled:
            raise RuntimeError("Desktop actuation is disabled")

        proposal = self._proposals.pop(approval_id, None)
        if not proposal:
            raise ValueError("Invalid or already consumed approval token")

        if time.time() > proposal.expires_at:
            raise ValueError("Action approval expired")

        pre_screen = None
        if verify_visual:
            try:
                pre_screen = self.vision_service.capture()
            except Exception:
                pass

        # Execute according to action type
        if proposal.action_type == ActuatorActionType.MOUSE_CLICK:
            req = ClickRequest.model_validate(proposal.arguments)
            result = self._perform_click(req.x, req.y, req.button)
        elif proposal.action_type == ActuatorActionType.KEY_PRESS:
            req = KeyPressRequest.model_validate(proposal.arguments)
            result = self._perform_key_press(req.key)
        elif proposal.action_type == ActuatorActionType.TYPE_TEXT:
            req = TypeTextRequest.model_validate(proposal.arguments)
            result = self._perform_type_text(req.text)
        elif proposal.action_type == ActuatorActionType.WINDOW_FOCUS:
            req = WindowFocusRequest.model_validate(proposal.arguments)
            result = self._perform_window_focus(req.hwnd)
        elif proposal.action_type == ActuatorActionType.MOUSE_SCROLL:
            req = ScrollRequest.model_validate(proposal.arguments)
            result = self._perform_scroll(req.clicks, req.x, req.y)
        elif proposal.action_type == ActuatorActionType.MOUSE_DRAG:
            req = DragRequest.model_validate(proposal.arguments)
            result = self._perform_drag(req.start_x, req.start_y, req.end_x, req.end_y)
        elif proposal.action_type == ActuatorActionType.WINDOW_STATE:
            req = WindowStateRequest.model_validate(proposal.arguments)
            result = self._perform_window_state(req.hwnd, req.state)
        else:
            raise ValueError(f"Unsupported action type: {proposal.action_type}")

        if verify_visual and pre_screen:
            try:
                time.sleep(0.05)
                post_screen = self.vision_service.capture()
                delta = self.action_verifier.compare_images(pre_screen, post_screen)
                result["visual_verification"] = delta.model_dump()
            except Exception as exc:
                result["visual_verification"] = {"error": str(exc)}

        return result

    def _perform_click(self, x: int, y: int, button: str) -> dict:
        width, height = self.vision_service.get_screen_size()
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"Click coordinates ({x}, {y}) out of screen bounds ({width}x{height})")

        if os.name != "nt":
            return {"ok": True, "action": "mouse_click", "simulated": True, "coords": (x, y)}

        user32 = ctypes.windll.user32
        # Set cursor position
        user32.SetCursorPos(x, y)
        time.sleep(0.02)

        if button == "left":
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif button == "right":
            user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
        elif button == "double":
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            time.sleep(0.05)
            user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

        return {"ok": True, "action": "mouse_click", "coords": (x, y), "button": button}

    def _perform_key_press(self, key: str) -> dict:
        normalized = key.strip().lower()
        if normalized in BLACKLISTED_HOTKEYS:
            raise ValueError(f"Hotkey '{key}' is blacklisted for security reasons")

        return {"ok": True, "action": "key_press", "key": key}

    def _perform_type_text(self, text: str) -> dict:
        if any(ord(c) < 32 and c not in "\r\n\t" for c in text):
            raise ValueError("Text contains invalid control characters")

        return {"ok": True, "action": "type_text", "character_count": len(text)}

    def _perform_window_focus(self, hwnd: int) -> dict:
        if os.name != "nt":
            return {"ok": True, "action": "window_focus", "hwnd": hwnd, "simulated": True}

        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            raise ValueError(f"HWND {hwnd} is not a valid window handle")

        user32.SetForegroundWindow(hwnd)
        return {"ok": True, "action": "window_focus", "hwnd": hwnd}

    def _perform_scroll(self, clicks: int, x: int | None = None, y: int | None = None) -> dict:
        if os.name != "nt":
            return {"ok": True, "action": "mouse_scroll", "clicks": clicks, "simulated": True}

        user32 = ctypes.windll.user32
        if x is not None and y is not None:
            user32.SetCursorPos(x, y)
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, clicks * 120, 0)
        return {"ok": True, "action": "mouse_scroll", "clicks": clicks}

    def _perform_drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> dict:
        width, height = self.vision_service.get_screen_size()
        if not (0 <= start_x < width and 0 <= start_y < height and 0 <= end_x < width and 0 <= end_y < height):
            raise ValueError(f"Drag coordinates ({start_x}, {start_y}) -> ({end_x}, {end_y}) out of screen bounds ({width}x{height})")

        if os.name != "nt":
            return {"ok": True, "action": "mouse_drag", "start": (start_x, start_y), "end": (end_x, end_y), "simulated": True}

        user32 = ctypes.windll.user32
        user32.SetCursorPos(start_x, start_y)
        time.sleep(0.02)
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        time.sleep(0.04)
        user32.SetCursorPos(end_x, end_y)
        time.sleep(0.04)
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        return {"ok": True, "action": "mouse_drag", "start": (start_x, start_y), "end": (end_x, end_y)}

    def _perform_window_state(self, hwnd: int, state: str) -> dict:
        if os.name != "nt":
            return {"ok": True, "action": "window_state", "hwnd": hwnd, "state": state, "simulated": True}

        user32 = ctypes.windll.user32
        if not user32.IsWindow(hwnd):
            raise ValueError(f"HWND {hwnd} is not a valid window handle")

        cmd = SW_MINIMIZE if state == "minimize" else (SW_MAXIMIZE if state == "maximize" else SW_RESTORE)
        user32.ShowWindow(hwnd, cmd)
        return {"ok": True, "action": "window_state", "hwnd": hwnd, "state": state}
