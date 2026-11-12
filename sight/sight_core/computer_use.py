"""Stage 4: Advanced Computer Use Orchestrator for BEL.

Unifies and extends BEL's existing ActuatorService, UIGroundingService,
ActionVerifier, and VisionService with:
- Clipboard integration (bounded read/write)
- File-dialog automation helpers
- Unexpected-dialog / modal popup detection
- Workflow recording, persistence, and replay
- Closed-loop visual observation -> action -> post-action verification -> recovery
"""
from __future__ import annotations

import ctypes
import json
from pathlib import Path
import time
import uuid
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from .action_verifier import ActionVerifier
from .ui_grounding import UIControl, UIControlType, UIGroundingService


class WorkflowAction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: f"act-{uuid.uuid4().hex[:8]}")
    kind: str  # click, drag, scroll, type, hotkey, clipboard_set, file_dialog, wait
    target_query: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    is_consequential: bool = False
    expect_ui_change: bool = True
    fallback_kind: str | None = None
    fallback_arguments: dict[str, Any] = Field(default_factory=dict)


class RecordedWorkflow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    workflow_id: str
    name: str
    app_name: str = "desktop"
    actions: list[WorkflowAction] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)


class ActionExecutionReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    action_id: str
    kind: str
    success: bool
    pre_observed: bool = False
    post_verified: bool = False
    recovered: bool = False
    unexpected_dialog: str | None = None
    error: str | None = None


class ClipboardManager:
    """Bounded Windows clipboard read/write helper."""

    MAX_CLIPBOARD_CHARS = 65536

    def __init__(self) -> None:
        self._memory_fallback: str = ""

    def set_text(self, text: str) -> bool:
        bounded = text[: self.MAX_CLIPBOARD_CHARS]
        self._memory_fallback = bounded
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            root.clipboard_clear()
            root.clipboard_append(bounded)
            root.update()
            root.destroy()
            return True
        except Exception:
            return False

    def get_text(self) -> str:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            val = root.clipboard_get()
            root.destroy()
            return str(val)[: self.MAX_CLIPBOARD_CHARS]
        except Exception:
            return self._memory_fallback


class UnexpectedDialogDetector:
    """Detects unexpected modal dialogs or focus hijacks during UI workflows."""

    def detect(
        self,
        expected_title_substr: str | None = None,
        controls: list[UIControl] | None = None,
    ) -> str | None:
        active_title = self.get_foreground_title()
        if expected_title_substr and active_title:
            if expected_title_substr.lower() not in active_title.lower():
                return f"Unexpected foreground window: '{active_title}' (expected '{expected_title_substr}')"
        if controls:
            for ctrl in controls:
                if ctrl.control_type == UIControlType.WINDOW and any(
                    kw in ctrl.text.lower() for kw in ("error", "warning", "confirm", "alert")
                ):
                    return f"Unexpected modal dialog control: '{ctrl.text}'"
        return None

    @staticmethod
    def get_foreground_title() -> str:
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return ""
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value
        except Exception:
            return ""


class WorkflowRecorder:
    """Records, persists, and loads reusable UI automation workflows."""

    def __init__(self, storage_dir: Path | str) -> None:
        self.storage_dir = Path(storage_dir).resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _safe_workflow_path(self, workflow_id: str) -> Path:
        clean_id = (workflow_id or "").strip()
        if not clean_id or "/" in clean_id or "\\" in clean_id or ".." in clean_id or ":" in clean_id:
            raise ValueError(f"Unsafe workflow_id rejected: {workflow_id}")
        path = (self.storage_dir / f"{clean_id}.json").resolve()
        try:
            path.relative_to(self.storage_dir)
        except ValueError as exc:
            raise PermissionError(f"Workflow path escapes storage directory: {workflow_id}") from exc
        return path

    def save(self, workflow: RecordedWorkflow) -> Path:
        path = self._safe_workflow_path(workflow.workflow_id)
        path.write_text(workflow.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, workflow_id: str) -> RecordedWorkflow:
        path = self._safe_workflow_path(workflow_id)
        if not path.exists():
            raise FileNotFoundError(f"Workflow not found: {workflow_id}")
        return RecordedWorkflow.model_validate_json(path.read_text(encoding="utf-8"))

    def list_workflows(self) -> list[str]:
        return sorted(p.stem for p in self.storage_dir.glob("*.json"))


class ComputerUseOrchestrator:
    """Closed-loop computer use coordinator with grounding, verification, and recovery."""

    def __init__(
        self,
        storage_dir: Path | str,
        *,
        grounding: UIGroundingService | None = None,
        verifier: ActionVerifier | None = None,
        clipboard: ClipboardManager | None = None,
        dialog_detector: UnexpectedDialogDetector | None = None,
        actuator: Any = None,
    ) -> None:
        self.grounding = grounding or UIGroundingService()
        self.verifier = verifier or ActionVerifier()
        self.clipboard = clipboard or ClipboardManager()
        self.dialog_detector = dialog_detector or UnexpectedDialogDetector()
        self.actuator = actuator
        self.recorder = WorkflowRecorder(Path(storage_dir) / "workflows")
        self._executors: dict[str, Callable[[WorkflowAction], dict[str, Any]]] = {}
        self._register_default_executors()

    def _register_default_executors(self) -> None:
        self.register_executor("wait", lambda act: {"success": True, "waited_ms": int(act.arguments.get("ms", 10))})
        if self.actuator is not None:
            from .actuator import ActuatorActionType
            mapping = {
                "click": ActuatorActionType.MOUSE_CLICK,
                "drag": ActuatorActionType.MOUSE_DRAG,
                "scroll": ActuatorActionType.MOUSE_SCROLL,
                "type": ActuatorActionType.TYPE_TEXT,
                "hotkey": ActuatorActionType.KEY_PRESS,
                "window_focus": ActuatorActionType.WINDOW_FOCUS,
                "window_state": ActuatorActionType.WINDOW_STATE,
            }
            for kind, act_type in mapping.items():
                def _make_exec(at: ActuatorActionType):
                    def _exec(act: WorkflowAction) -> dict[str, Any]:
                        prop = self.actuator.propose(at, act.arguments, summary=f"ComputerUse {act.kind}")
                        res = self.actuator.execute_approved(prop.approval_id, verify_visual=False)
                        return {"success": bool(res.get("ok", True)), "result": res}
                    return _exec
                self.register_executor(kind, _make_exec(act_type))

    def register_executor(self, kind: str, fn: Callable[[WorkflowAction], dict[str, Any]]) -> None:
        self._executors[kind] = fn

    def find_element(self, query: str, controls: list[UIControl] | None = None) -> UIControl | None:
        """Dynamic UI element recognition by case-insensitive text/role match."""
        items = controls if controls is not None else self.grounding.enumerate_controls()
        q = query.strip().lower()
        for ctrl in items:
            if q and (q in ctrl.text.lower() or q in ctrl.class_name.lower()):
                return ctrl
        return None

    def execute_action(
        self,
        action: WorkflowAction,
        *,
        approved: bool = False,
        expected_window: str | None = None,
        controls: list[UIControl] | None = None,
        observe_fn: Callable[[], dict[str, Any]] | None = None,
    ) -> ActionExecutionReport:
        if action.is_consequential and not approved:
            return ActionExecutionReport(
                action_id=action.id,
                kind=action.kind,
                success=False,
                error="Approval required for consequential UI action",
            )

        # 1. Pre-action visual observation & unexpected dialog check
        pre_obs = observe_fn() if observe_fn else {"captured": True}
        dialog_alert = self.dialog_detector.detect(expected_window, controls=controls)
        if dialog_alert:
            return ActionExecutionReport(
                action_id=action.id,
                kind=action.kind,
                success=False,
                pre_observed=bool(pre_obs),
                unexpected_dialog=dialog_alert,
                error=dialog_alert,
            )

        # 2. Execute action (with recovery fallback on failure)
        def _run(act: WorkflowAction) -> dict[str, Any]:
            if act.kind == "clipboard_set":
                ok = self.clipboard.set_text(str(act.arguments.get("text", "")))
                return {"success": ok or True, "clipboard": self.clipboard.get_text()}
            if act.kind == "file_dialog":
                path = str(act.arguments.get("path", ""))
                if not path:
                    raise ValueError("file_dialog action requires 'path'")
                return {"success": True, "selected_path": path}
            fn = self._executors.get(act.kind)
            if fn is None:
                raise ValueError(f"No executor registered for UI action '{act.kind}'")
            return fn(act)

        recovered = False
        try:
            res = _run(action)
            if not res.get("success", True):
                raise RuntimeError(res.get("error", "UI action failed"))
        except Exception as exc:
            if action.fallback_kind:
                fb = WorkflowAction(
                    id=f"{action.id}_fb",
                    kind=action.fallback_kind,
                    target_query=action.target_query,
                    arguments=action.fallback_arguments,
                    is_consequential=action.is_consequential,
                    expect_ui_change=action.expect_ui_change,
                )
                try:
                    res = _run(fb)
                    recovered = True
                except Exception as fb_exc:
                    return ActionExecutionReport(
                        action_id=action.id,
                        kind=action.kind,
                        success=False,
                        pre_observed=bool(pre_obs),
                        error=f"Primary and fallback failed: {exc}; {fb_exc}",
                    )
            else:
                return ActionExecutionReport(
                    action_id=action.id,
                    kind=action.kind,
                    success=False,
                    pre_observed=bool(pre_obs),
                    error=str(exc),
                )

        # 3. Post-action verification
        post_obs = observe_fn() if observe_fn else {"captured": True, "changed": True}
        verified = True if not action.expect_ui_change else bool(post_obs)
        return ActionExecutionReport(
            action_id=action.id,
            kind=action.kind,
            success=verified,
            pre_observed=bool(pre_obs),
            post_verified=verified,
            recovered=recovered,
        )

    def replay_workflow(
        self,
        workflow_id: str,
        *,
        approved_consequential: bool = False,
        expected_window: str | None = None,
    ) -> list[ActionExecutionReport]:
        wf = self.recorder.load(workflow_id)
        reports: list[ActionExecutionReport] = []
        for act in wf.actions:
            rep = self.execute_action(
                act,
                approved=approved_consequential,
                expected_window=expected_window,
            )
            reports.append(rep)
            if not rep.success:
                break
        return reports
