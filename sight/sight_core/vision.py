"""Multimodal vision perception and screen observation subsystem.

Captures bounded desktop display regions with privacy-preserving redaction,
enumerates window bounding boxes, and performs UI coordinate grounding.
All capture operations run locally with zero network transmission.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import io
import logging
import os
import re
from typing import Literal

from PIL import Image, ImageDraw, ImageFilter, ImageGrab
from pydantic import Field

from .tools import StrictModel

logger = logging.getLogger(__name__)

SENSITIVE_TITLE_PATTERNS = [
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"bitwarden", re.IGNORECASE),
    re.compile(r"1password", re.IGNORECASE),
    re.compile(r"keepass", re.IGNORECASE),
    re.compile(r"authenticator", re.IGNORECASE),
    re.compile(r"incognito", re.IGNORECASE),
    re.compile(r"private\s+browsing", re.IGNORECASE),
    re.compile(r"inprivate", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"vault", re.IGNORECASE),
]


class VisionUnavailable(RuntimeError):
    pass


class BoundingBox(StrictModel):
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def box_tuple(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


class WindowBounds(StrictModel):
    hwnd: int
    title: str
    rect: BoundingBox
    is_foreground: bool
    is_sensitive: bool


class CaptureOptions(StrictModel):
    bbox: BoundingBox | None = None
    max_dimension: int = Field(default=1920, ge=320, le=3840)
    format: Literal["jpeg", "png"] = "jpeg"
    quality: int = Field(default=85, ge=10, le=100)
    redact_sensitive: bool = True


class VisionService:
    """Provides local screen capture, window inspection, and privacy-preserving vision grounding."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def get_screen_size(self) -> tuple[int, int]:
        """Returns the primary screen width and height in pixels."""
        if os.name == "nt":
            user32 = ctypes.windll.user32
            width = user32.GetSystemMetrics(0)
            height = user32.GetSystemMetrics(1)
            if width > 0 and height > 0:
                return (width, height)
        # Fallback via Pillow
        try:
            with ImageGrab.grab() as probe:
                return probe.size
        except Exception:
            return (1920, 1080)

    def is_title_sensitive(self, title: str) -> bool:
        if not title:
            return False
        return any(pattern.search(title) for pattern in SENSITIVE_TITLE_PATTERNS)

    def list_windows(self, include_empty: bool = False) -> list[WindowBounds]:
        """Enumerates visible top-level windows and their bounding rectangles."""
        if os.name != "nt":
            return []

        user32 = ctypes.windll.user32
        foreground_hwnd = user32.GetForegroundWindow()
        windows: list[WindowBounds] = []

        enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def enum_callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            title = ""
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value.strip()

            if not title and not include_empty:
                return True

            rect = wintypes.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True

            width = rect.right - rect.left
            height = rect.bottom - rect.top

            # Discard zero-size, minimized, or off-screen ghost windows
            if width <= 0 or height <= 0 or rect.left < -10000 or rect.top < -10000:
                return True

            # Normalize negative left/top if partially off-screen
            left = max(0, rect.left)
            top = max(0, rect.top)

            is_sensitive = self.is_title_sensitive(title)
            is_foreground = hwnd == foreground_hwnd

            windows.append(
                WindowBounds(
                    hwnd=hwnd,
                    title="[REDACTED_SENSITIVE_WINDOW]" if is_sensitive else title,
                    rect=BoundingBox(left=left, top=top, width=width, height=height),
                    is_foreground=is_foreground,
                    is_sensitive=is_sensitive,
                )
            )
            return True

        user32.EnumWindows(enum_proc_type(enum_callback), 0)
        return windows

    def ground_point(self, x: int, y: int) -> WindowBounds | None:
        """Finds the topmost visible window bounding box containing the coordinate (x, y)."""
        windows = self.list_windows()
        for win in windows:
            r = win.rect
            if r.left <= x <= r.right and r.top <= y <= r.bottom:
                return win
        return None

    def capture(self, options: CaptureOptions | None = None) -> bytes:
        """Captures a desktop frame with privacy redaction and dimension bounding."""
        if not self.enabled:
            raise RuntimeError("Vision perception subsystem is disabled")

        opts = options or CaptureOptions()

        # Step 1: Capture screen or bounded crop
        bbox = opts.bbox.box_tuple if opts.bbox else None
        try:
            image = ImageGrab.grab(bbox=bbox)
        except OSError as exc:
            raise VisionUnavailable(f"Screen capture unavailable in current desktop session: {exc}") from exc

        try:
            # Step 2: Apply privacy redaction for sensitive windows if requested
            if opts.redact_sensitive:
                sensitive_windows = [w for w in self.list_windows() if w.is_sensitive]
                if sensitive_windows:
                    offset_x = opts.bbox.left if opts.bbox else 0
                    offset_y = opts.bbox.top if opts.bbox else 0

                    draw = ImageDraw.Draw(image)
                    for win in sensitive_windows:
                        box = win.rect
                        # Transform to local crop coordinates
                        crop_l = max(0, box.left - offset_x)
                        crop_t = max(0, box.top - offset_y)
                        crop_r = min(image.width, box.right - offset_x)
                        crop_b = min(image.height, box.bottom - offset_y)

                        if crop_r > crop_l and crop_b > crop_t:
                            # Apply black privacy box with privacy label
                            draw.rectangle((crop_l, crop_t, crop_r, crop_b), fill=(18, 18, 20), outline=(239, 68, 68), width=2)
                            label = "[PRIVACY REDACTED]"
                            draw.text((crop_l + 10, crop_t + 10), label, fill=(239, 68, 68))

            # Step 3: Resize proportionally if dimensions exceed max_dimension
            max_d = opts.max_dimension
            if image.width > max_d or image.height > max_d:
                scale = min(max_d / image.width, max_d / image.height)
                new_width = max(1, int(image.width * scale))
                new_height = max(1, int(image.height * scale))
                image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

            # Step 4: Encode to requested format
            buffer = io.BytesIO()
            if opts.format == "jpeg":
                rgb_image = image.convert("RGB")
                rgb_image.save(buffer, format="JPEG", quality=opts.quality, optimize=True)
            else:
                image.save(buffer, format="PNG", optimize=True)

            return buffer.getvalue()
        finally:
            image.close()

    def status(self) -> dict:
        width, height = self.get_screen_size()
        windows = self.list_windows() if os.name == "nt" else []
        return {
            "enabled": self.enabled,
            "available": True,
            "resolution": {"width": width, "height": height},
            "active_windows_count": len(windows),
            "foreground_window": next((w.title for w in windows if w.is_foreground), None),
            "privacy_redaction_active": True,
        }
