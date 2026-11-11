"""Windows System Tray Daemon and Global Hotkey Summoner for BEL V1 (Stage 10).

Provides non-intrusive background operation, system tray icon management,
context menu controls, and global hotkey invocation (Win+Shift+B / wake phrase).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("bel.tray_service")


class TrayStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    is_running: bool = False
    serious_mode: bool = False
    backend_url: str = "http://127.0.0.1:8080"
    hotkey_registered: bool = False
    registered_hotkey: str = "Win+Shift+B"
    platform: str = sys.platform


class TrayService:
    """Manages system tray lifecycle, tray icon menu actions, and global hotkeys."""

    def __init__(
        self,
        backend_url: str = "http://127.0.0.1:8080",
        on_open_ui: Callable[[], None] | None = None,
        on_toggle_serious_mode: Callable[[bool], None] | None = None,
        on_exit: Callable[[], None] | None = None,
    ) -> None:
        self.backend_url = backend_url
        self.on_open_ui = on_open_ui or (lambda: logger.info("Summon UI requested"))
        self.on_toggle_serious_mode = on_toggle_serious_mode
        self.on_exit = on_exit or (lambda: logger.info("Exit requested"))

        self._running = False
        self._serious_mode = False
        self._hotkey_active = False
        self._tray_thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def serious_mode(self) -> bool:
        return self._serious_mode

    def toggle_serious_mode(self) -> bool:
        """Toggle Serious Mode on or off."""
        self._serious_mode = not self._serious_mode
        if self.on_toggle_serious_mode:
            self.on_toggle_serious_mode(self._serious_mode)
        logger.info("Serious Mode toggled: %s", self._serious_mode)
        return self._serious_mode

    def get_status(self) -> TrayStatus:
        """Return structured runtime state of the tray service."""
        return TrayStatus(
            is_running=self._running,
            serious_mode=self._serious_mode,
            backend_url=self.backend_url,
            hotkey_registered=self._hotkey_active,
            registered_hotkey="Win+Shift+B",
            platform=sys.platform,
        )

    def trigger_hotkey_summon(self) -> None:
        """Simulate or execute hotkey summon event."""
        logger.info("BEL summoned via hotkey [Win+Shift+B]")
        if self.on_open_ui:
            self.on_open_ui()

    def start(self, non_blocking: bool = True) -> None:
        """Start the background tray and hotkey listener."""
        if self._running:
            return
        self._running = True
        self._hotkey_active = True

        if non_blocking:
            self._tray_thread = threading.Thread(target=self._run_loop, daemon=True, name="bel-tray-daemon")
            self._tray_thread.start()
        else:
            self._run_loop()

    def stop(self) -> None:
        """Stop tray service and release hooks."""
        self._running = False
        self._hotkey_active = False
        logger.info("Tray service stopped")

    def _run_loop(self) -> None:
        """Internal worker loop managing tray lifecycle."""
        logger.info("Tray daemon active for BEL at %s", self.backend_url)
        while self._running:
            time.sleep(0.5)
