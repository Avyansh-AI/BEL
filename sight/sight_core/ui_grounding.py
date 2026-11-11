"""UI control grounding and spatial element inspection subsystem.

Enumerates Win32 controls (buttons, input fields, labels, combo boxes)
and resolves user spatial targets to exact GUI element bounding boxes.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from enum import Enum
import logging
import os
import re

from .tools import StrictModel
from .vision import BoundingBox, VisionService

logger = logging.getLogger(__name__)


class UIControlType(str, Enum):
    BUTTON = "button"
    EDIT = "edit"
    LABEL = "label"
    COMBOBOX = "combobox"
    WINDOW = "window"
    GENERIC = "generic"


class UIControl(StrictModel):
    hwnd: int
    class_name: str
    control_type: UIControlType
    text: str
    bounding_box: BoundingBox
    is_enabled: bool
    is_visible: bool


def classify_control_class(class_name: str) -> UIControlType:
    c = class_name.lower()
    if "button" in c:
        return UIControlType.BUTTON
    elif "edit" in c:
        return UIControlType.EDIT
    elif "static" in c:
        return UIControlType.LABEL
    elif "combobox" in c or "dropdown" in c:
        return UIControlType.COMBOBOX
    elif "window" in c or "dialog" in c:
        return UIControlType.WINDOW
    return UIControlType.GENERIC


class UIGroundingService:
    """Discovers, enumerates, and spatially resolves desktop GUI elements."""

    def __init__(self, vision_service: VisionService | None = None):
        self.vision_service = vision_service or VisionService()

    def enumerate_controls(self, parent_hwnd: int | None = None) -> list[UIControl]:
        """Enumerates child controls of a window, or active top-level windows."""
        if os.name != "nt":
            return []

        user32 = ctypes.windll.user32
        target_hwnd = parent_hwnd or user32.GetForegroundWindow()
        if not target_hwnd or not user32.IsWindow(target_hwnd):
            return []

        controls: list[UIControl] = []

        def enum_child_callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True

            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True

            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width <= 0 or height <= 0:
                return True

            cname_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cname_buf, 256)
            class_name = cname_buf.value.strip()

            text_buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, text_buf, 512)
            text = text_buf.value.strip()

            is_enabled = bool(user32.IsWindowEnabled(hwnd))
            control_type = classify_control_class(class_name)

            controls.append(
                UIControl(
                    hwnd=hwnd,
                    class_name=class_name,
                    control_type=control_type,
                    text=text,
                    bounding_box=BoundingBox(
                        left=max(0, rect.left),
                        top=max(0, rect.top),
                        width=width,
                        height=height,
                    ),
                    is_enabled=is_enabled,
                    is_visible=True,
                )
            )
            return True

        proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumChildWindows(target_hwnd, proc_type(enum_child_callback), 0)
        return controls

    def find_control_by_text(self, text_query: str, parent_hwnd: int | None = None) -> UIControl | None:
        """Finds the first interactive control whose text matches the query."""
        if not text_query:
            return None
        q = text_query.strip().lower()
        controls = self.enumerate_controls(parent_hwnd)
        for ctrl in controls:
            if q in ctrl.text.lower():
                return ctrl
        return None

    def ground_coordinate(self, x: int, y: int, parent_hwnd: int | None = None) -> UIControl | None:
        """Finds the innermost child control enclosing the coordinate (x, y)."""
        controls = self.enumerate_controls(parent_hwnd)
        matched = []
        for ctrl in controls:
            b = ctrl.bounding_box
            if b.left <= x <= b.right and b.top <= y <= b.bottom:
                matched.append(ctrl)
        if not matched:
            return None
        # Sort by smallest area (innermost control)
        matched.sort(key=lambda c: c.bounding_box.width * c.bounding_box.height)
        return matched[0]
