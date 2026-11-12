"""Windows desktop host. The JS bridge controls presentation, never tool authority."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import threading
import time

from .config import Config
from .security import private_directory, safe_file, atomic_private_write


def _winforms_action(callback):
    # Optional desktop dependency stays lazy for headless server/CLI users.
    from System import Action
    return Action(callback)


def dispatch_to_window(window, callback, timeout=5):
    """Marshal native changes to WinForms without holding a caller-side lock.

    pywebview 6.2's on_top setter writes Form.TopMost directly. Calling that
    setter from its JS/tray worker can deadlock the native message loop. A
    posted delegate keeps every lifecycle mutation on the owning GUI thread.
    """
    native = window.native
    if native is None or native.IsDisposed:
        raise RuntimeError('Desktop window is not ready')
    if not native.InvokeRequired:
        return callback()
    completed, expired = threading.Event(), threading.Event()
    result = {}

    def apply():
        try:
            if not expired.is_set():
                result['value'] = callback()
        except Exception as exc:
            result['error'] = exc
        finally:
            completed.set()

    native.BeginInvoke(_winforms_action(apply))
    if not completed.wait(timeout):
        expired.set()
        raise RuntimeError('Desktop operation exceeded its deadline')
    if 'error' in result:
        raise result['error']
    return result.get('value')


class DesktopController:
    def __init__(self, dispatch=dispatch_to_window):
        self.window = None
        self.tray = None
        self.mode = "active"
        self.tray_ready = threading.Event()
        self.quitting = False
        self.smoke_passed = None
        self.lock = threading.RLock()
        self._dispatch = dispatch

    def status(self):
        return {"available": True, "mode": self.mode, "tray_available": self.tray_ready.is_set(),
                "wake_available": False, "microphone_enabled": False}

    def set_mode(self, mode):
        if mode not in {"active", "compact", "background"}:
            raise ValueError("Unsupported desktop mode")
        if self.window is None:
            raise RuntimeError("Desktop window unavailable")

        def apply():
            # The native message queue serializes these mutations. Do not hold
            # a Python lock across native calls: close/status must remain usable
            # even if Windows does not complete a transition within its deadline.
            if self.quitting:
                raise RuntimeError("Desktop window unavailable")
            if mode == "background":
                if not self.tray_ready.is_set():
                    raise RuntimeError("System tray unavailable; the window will remain visible")
                self.window.hide()
            else:
                self.window.on_top = mode == "compact"
                self.window.resize(*( (380, 480) if mode == "compact" else (1100, 800)))
                self.window.show()
                self.window.restore()
            self.mode = mode
            # Do not synchronously evaluate_js on the GUI thread: WebView2
            # completes that operation on this same thread. Native script
            # submission is asynchronous and carries presentation state only.
            try:
                script = "window.dispatchEvent(new CustomEvent('bel-native-mode', {detail: " + json.dumps({"mode": mode}) + "}));"
                self.window.native.browser.webview.ExecuteScriptAsync(script)
            except Exception:
                pass  # status() remains authoritative if the renderer is gone.
            return self.status()
        return self._dispatch(self.window, apply)

    def close_app(self):
        # Retain the tray until closure succeeds. A timed-out queued operation
        # must not leave a hidden application without any way to restore it.
        with self.lock:
            self.quitting = True
        try:
            if self.window is not None:
                self._dispatch(self.window, self.window.destroy)
        except Exception:
            with self.lock:
                self.quitting = False
            raise
        if self.tray is not None:
            self.tray.stop()
        return {"closing": True}

    def on_closing(self):
        if not self.quitting and self.tray_ready.is_set():
            # FormClosing runs on the WinForms UI thread. Never wait there for JS.
            threading.Thread(target=self.set_mode, args=("background",), daemon=True).start()
            return False
        return True


class DesktopBridge:
    """Exactly three exposed methods; controller objects are private to Python."""
    def __init__(self, controller):
        self._controller = controller

    def status(self):
        return self._controller.status()

    def set_mode(self, mode):
        return self._controller.set_mode(mode)

    def close_app(self):
        return self._controller.close_app()


class BackendHost:
    def __init__(self, config):
        self.config = config
        self.server = self.thread = self.socket = None

    def start(self):
        import uvicorn
        from .api import create_app
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            self.socket.bind(("127.0.0.1", self.config.port))
            self.socket.listen(128)
            self.socket.setblocking(False)
            app = create_app(self.config)
            self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.config.port,
                workers=1, access_log=False, log_config=None, ws_max_size=40000, server_header=False,
                timeout_graceful_shutdown=5))
            self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]},
                                           name="BEL backend", daemon=True)
            self.thread.start()
            deadline = time.monotonic() + 20
            while not self.server.started:
                if not self.thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("BEL backend did not start")
                time.sleep(.025)
            return f"http://127.0.0.1:{self.config.port}/#sight-session={app.state.bootstrap_token}"
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=12)
        if self.socket:
            self.socket.close()


def configure_logging(data_dir):
    private_directory(data_dir)
    for suffix in ("", ".1", ".2"):
        safe_file(data_dir / ("desktop.log" + suffix))
    logger = logging.getLogger("bel.desktop")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(data_dir / "desktop.log", maxBytes=500000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger.addHandler(handler)
    return logger


def tray_icon(controller):
    import pystray
    from PIL import Image, ImageDraw
    # Small native tray glyph, independent of the official frontend orb artwork.
    icon = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(icon)
    draw.ellipse((7, 7, 57, 57), fill="#0c63c9", outline="#a6e6ff", width=4)
    draw.ellipse((18, 12, 36, 23), fill="#b7e8ff")
    controller.tray = pystray.Icon("BEL", icon, "BEL — Behavioral Executive Logic", menu=pystray.Menu(
        pystray.MenuItem("Open BEL", lambda *_: controller.set_mode("active"), default=True),
        pystray.MenuItem("Compact orb", lambda *_: controller.set_mode("compact")),
        pystray.MenuItem("Background", lambda *_: controller.set_mode("background")),
        pystray.MenuItem("Exit BEL", lambda *_: controller.close_app())))

    def setup(tray):
        tray.visible = True
        controller.tray_ready.set()

    def run():
        try:
            controller.tray.run(setup)
        finally:
            controller.tray_ready.clear()
    thread = threading.Thread(target=run, name="BEL tray", daemon=True)
    thread.start()
    return thread


def set_autostart(enabled):
    """Explicit local CLI action, never enabled by installation or first launch."""
    if os.name != "nt" or not getattr(sys, "frozen", False):
        raise RuntimeError("Auto-start requires the packaged Windows application")
    import winreg
    path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            import subprocess
            winreg.SetValueEx(key, "BEL", 0, winreg.REG_SZ,
                             subprocess.list2cmdline([sys.executable, "--background"]))
        else:
            try:
                winreg.DeleteValue(key, "BEL")
            except FileNotFoundError:
                pass


def smoke_probe(controller, host, report, started):
    """Explicit test-only lifecycle exercise; no model, microphone or user tools."""
    result = {"kind": "real_windows_desktop", "checks": {}, "packaged": bool(getattr(sys, "frozen", False))}
    def stage(name):
        atomic_private_write(report.with_suffix('.progress.json'), json.dumps({'stage': name, 'checks': result['checks']}).encode())
    try:
        window = controller.window
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            loaded = window.evaluate_js("({title:document.title, text:document.body.innerText, ready:!!window.pywebview, rendered:!!document.querySelector('#root > *'), bridgeMethods:Object.keys(window.pywebview?.api||{}), url:location.pathname})")
            atomic_private_write(report.with_suffix('.progress.json'), json.dumps({'stage': 'renderer', 'title': loaded.get('title'), 'rendered': loaded.get('rendered'), 'bridgeMethods': loaded.get('bridgeMethods'), 'url': loaded.get('url'), 'body_length': len(loaded.get('text', ''))}).encode())
            if loaded.get("ready") and loaded.get('rendered') and "BEL" in loaded.get("title", ""):
                break
            time.sleep(.1)
        result["startup_seconds"] = round(time.monotonic() - started, 3)
        result["checks"]["frontend_loaded"] = loaded.get('rendered') is True and "BEL" in loaded.get("title", "") and len(loaded.get("text", "")) > 20
        result["checks"]["bridge_loaded"] = loaded.get("ready") is True
        controller.tray_ready.wait(5)
        result["checks"]["tray_ready"] = controller.tray_ready.is_set()
        # Real renderer fetch uses the normal owner-session bootstrap and cookies.
        pending, health = threading.Event(), {}
        def received(value):
            health.update(value if isinstance(value, dict) else {})
            pending.set()
        # React establishes its authenticated session after DOM load. Poll only a
        # read endpoint; never claim independently or bypass frontend bootstrap.
        window.evaluate_js("(async()=>{let status=0;for(let i=0;i<40;i++){try{status=(await fetch('/api/health')).status}catch{}if(status===200)return{status};await new Promise(r=>setTimeout(r,200))}return{status}})()", received)
        pending.wait(10)
        result["checks"]["authenticated_api"] = health.get("status") == 200
        stage('compact')
        controller.set_mode("compact")
        result["checks"]["compact"] = controller.mode == "compact"
        stage('background')
        controller.set_mode("background")
        import ctypes
        from ctypes import wintypes
        is_visible = ctypes.windll.user32.IsWindowVisible
        is_visible.argtypes = [wintypes.HWND]
        native_handle = window.native.Handle.ToInt64()
        result["checks"]["background_backend_running"] = host.thread.is_alive() and controller.mode == "background"
        result["checks"]["native_window_hidden"] = not bool(is_visible(native_handle))
        stage('restore')
        controller.set_mode("active")
        result["checks"]["restore"] = controller.mode == "active" and bool(is_visible(native_handle))
        result["checks"]["no_console"] = not bool(__import__('ctypes').windll.kernel32.GetConsoleWindow())
        result["status"] = "PASS" if all(result["checks"].values()) else "FAIL"
    except Exception as exc:
        result["status"] = "FAIL"
        result["error_type"] = type(exc).__name__
    finally:
        controller.smoke_passed = result.get('status') == 'PASS'
        atomic_private_write(report, json.dumps(result, indent=2).encode())
        controller.close_app()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="BEL")
    parser.add_argument("--background", action="store_true")
    parser.add_argument('--local-dictation', action='store_true', help='Offer local Windows dictation; microphone capture still requires session consent and hold-to-talk')
    parser.add_argument('--local-tts', action='store_true', help='Offer local Windows speech synthesis (TTS)')
    parser.add_argument("--data-directory", type=Path)
    parser.add_argument("--port", type=int)
    parser.add_argument("--smoke-test", type=Path, help="Exercise only BEL's own desktop lifecycle and exit with a JSON report")
    auto = parser.add_mutually_exclusive_group()
    auto.add_argument("--enable-autostart", action="store_true")
    auto.add_argument("--disable-autostart", action="store_true")
    args = parser.parse_args(argv)
    started = time.monotonic()
    host = controller = logger = None
    try:
        if os.name != "nt":
            raise RuntimeError("This desktop launcher requires Windows")
        if args.enable_autostart or args.disable_autostart:
            set_autostart(args.enable_autostart)
            return 0
        config = Config.from_env()
        if args.local_dictation:
            config = replace(config, local_stt=True)
        if args.local_tts:
            config = replace(config, local_tts=True)
        if args.data_directory:
            from .config import read_local_model, environment_value
            directory = args.data_directory.absolute()
            saved = read_local_model(directory)
            config = replace(config, data_dir=directory,
                             model=environment_value("OLLAMA_MODEL", saved.get("model", "")), thinking=saved.get("thinking"))
        if args.port is not None:
            if not 1024 <= args.port <= 65535:
                raise ValueError("BEL port must be between 1024 and 65535")
            config = replace(config, port=args.port)
        # This release's owner-approved default applies only to a fresh profile.
        # Explicit environment selections (including empty) and saved files win.
        if (not config.model and not (config.data_dir / 'local-model.json').exists()
                and not any(key in os.environ for key in ('BEL_OLLAMA_MODEL', 'SIGHT_OLLAMA_MODEL'))
                and not args.smoke_test):
            from .models import OFFICIAL_GEMMA
            config = replace(config, model=OFFICIAL_GEMMA, thinking=True)
        logger = configure_logging(config.data_dir)
        from .cli import single_instance
        with single_instance(config.data_dir):
            import webview
            logging.getLogger("pywebview").disabled = True  # Never log session-bearing navigation URLs.
            host = BackendHost(config)
            url = host.start()
            controller = DesktopController()
            controller.window = webview.create_window("BEL — Behavioral Executive Logic", url,
                js_api=DesktopBridge(controller), width=1100, height=800, min_size=(320, 400),
                background_color="#050609", text_select=True)
            controller.window.events.closing += controller.on_closing
            tray_icon(controller)
            if args.smoke_test:
                controller.window.events.loaded += lambda: threading.Thread(target=smoke_probe,
                    args=(controller, host, args.smoke_test.absolute(), started), daemon=True).start()
            elif args.background:
                def hide_after_load():
                    if controller.tray_ready.wait(3):
                        controller.set_mode("background")
                controller.window.events.loaded += hide_after_load
            else:
                def focus_after_load():
                    try:
                        controller.set_mode("active")
                        import ctypes
                        hwnd = controller.window.native.Handle.ToInt64()
                        ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        ctypes.windll.user32.SetForegroundWindow(hwnd)
                    except Exception:
                        pass
                controller.window.events.loaded += focus_after_load
            logger.info("desktop.start; dictation=%s; microphone requires session consent; wake model unavailable", config.local_stt)
            try:
                webview.start(gui="edgechromium", debug=False, private_mode=True)
            finally:
                controller.quitting = True
                if controller.tray:
                    controller.tray.stop()
                host.stop()
            logger.info("desktop.stopped")
        return 1 if args.smoke_test and controller.smoke_passed is not True else 0
    except Exception as exc:
        if host:
            host.stop()
        if logger:
            logger.error("desktop.failed: %s", type(exc).__name__)
        if args.smoke_test:
            atomic_private_write(args.smoke_test.absolute(), json.dumps({"status": "FAIL", "error_type": type(exc).__name__}).encode())
        else:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                "BEL could not start. Check desktop.log in your data directory, the WebView2 runtime, "
                "and whether another BEL instance owns the data directory or port. No data was deleted.", "BEL startup", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
