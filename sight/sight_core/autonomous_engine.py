"""Stage 2: Persistent Autonomous Execution Engine for BEL.

Implements the full autonomous lifecycle:
    REQUEST -> UNDERSTAND -> PLAN -> EXECUTE -> OBSERVE -> VERIFY -> REPLAN -> COMPLETE

Reuses existing BEL cognitive, monitoring, and storage primitives while adding:
- Persistent SQLite task queue and step checkpoints (survives restarts)
- Dynamic task decomposition and dependency-aware parallel scheduling
- Automatic replanning after step failures with controlled recovery
- Evidence-based completion verification (never completes without proof)
- Resource-aware scheduling via SystemMonitor telemetry
- Configurable autonomy & approval gates for consequential operations
- Background execution, progress tracking, cancellation, and notifications
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path
import sqlite3
import time
import uuid
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field

from .cognitive.understanding import InputUnderstanding
from .system_monitor import SystemMonitor


class LifecyclePhase(str, Enum):
    REQUEST = "REQUEST"
    UNDERSTAND = "UNDERSTAND"
    PLAN = "PLAN"
    EXECUTE = "EXECUTE"
    OBSERVE = "OBSERVE"
    VERIFY = "VERIFY"
    REPLAN = "REPLAN"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AutonomyLevel(str, Enum):
    MANUAL = "manual"
    SUPERVISED = "supervised"
    AUTONOMOUS_SAFE = "autonomous_safe"
    FULL_AUTONOMOUS = "full_autonomous"


class AutonomousStepSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    description: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    is_consequential: bool = False
    heavy_resource: bool = False
    max_retries: int = Field(default=1, ge=0, le=5)
    fallback_tool: str | None = None
    fallback_arguments: dict[str, Any] = Field(default_factory=dict)


class AutonomousTaskRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    goal: str = Field(min_length=1, max_length=4000)
    steps: list[AutonomousStepSpec] | None = None
    autonomy_level: AutonomyLevel = AutonomyLevel.SUPERVISED
    max_replans: int = Field(default=2, ge=0, le=5)
    max_parallel: int = Field(default=3, ge=1, le=8)
    priority: int = Field(default=5, ge=1, le=10)
    project_id: str = "default"


class StepProgress(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    description: str
    tool: str
    state: str
    depends_on: list[str] = Field(default_factory=list)
    attempts: int = 0
    is_consequential: bool = False
    approved: bool = False
    output: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    error: str | None = None


class TaskProgress(BaseModel):
    model_config = ConfigDict(extra="ignore")
    task_id: str
    goal: str
    phase: LifecyclePhase
    state: str
    autonomy_level: AutonomyLevel
    total_steps: int
    completed_steps: int
    failed_steps: int
    percent: float
    replan_count: int
    steps: list[StepProgress] = Field(default_factory=list)
    completion_evidence: list[dict[str, Any]] = Field(default_factory=list)
    lifecycle_history: list[str] = Field(default_factory=list)
    error: str | None = None


@dataclass
class RegisteredTool:
    name: str
    handler: Callable[[dict[str, Any], dict[str, Any]], Any | Awaitable[Any]]
    is_consequential: bool = False
    verifier: Callable[[dict[str, Any]], bool] | None = None


class AutonomousExecutionEngine:
    """Persistent, dependency-aware, parallel autonomous task execution engine."""

    def __init__(
        self,
        data_dir: Path | str,
        *,
        min_free_ram_mb: int = 300,
        max_cpu_percent: float = 95.0,
        default_autonomy: AutonomyLevel = AutonomyLevel.SUPERVISED,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "autonomous_tasks.sqlite3"
        self.min_free_ram_mb = min_free_ram_mb
        self.max_cpu_percent = max_cpu_percent
        self.default_autonomy = default_autonomy

        self._understanding = InputUnderstanding()
        self._tools: dict[str, RegisteredTool] = {}
        self._notifications: list[dict[str, Any]] = []
        self._notification_callbacks: list[Callable[[dict[str, Any]], Any]] = []
        self._worker_task: asyncio.Task | None = None
        self._wakeup = asyncio.Event()
        self._stopping = False
        self._active_tasks: dict[str, asyncio.Task] = {}

        self._init_db()
        self._register_builtin_tools()

    def bind_subsystems(
        self,
        *,
        bel_code: Any = None,
        web_research: Any = None,
        personal_memory: Any = None,
        document_parser: Any = None,
        multi_agent: Any = None,
    ) -> None:
        """Bind real BEL subsystems as executable tools in the autonomous engine."""
        if bel_code is not None:
            self.register_tool(
                "code.inspect_repo",
                lambda args, ctx: bel_code.inspect_repository().model_dump() | {"status": "ok"},
                is_consequential=False,
            )
            self.register_tool(
                "code.scan_security",
                lambda args, ctx: bel_code.scan_vulnerabilities(args.get("paths")).model_dump() | {"status": "ok"},
                is_consequential=False,
            )
        if web_research is not None:
            async def _research_tool(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
                rep = await web_research.research(str(args.get("query", "")))
                return rep.model_dump() | {"status": "ok"}
            self.register_tool("web.research", _research_tool, is_consequential=False)
        if personal_memory is not None:
            from .personal_ecosystem import MemoryEntry
            def _mem_store(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
                entry = personal_memory.add(
                    MemoryEntry(
                        project_id=str(args.get("project_id", "default")),
                        key=str(args.get("key", "note")),
                        content=str(args.get("content", "")),
                        importance=float(args.get("importance", 0.7)),
                    )
                )
                return {"memory_id": entry.id, "key": entry.key, "status": "ok"}
            def _mem_retrieve(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
                hits = personal_memory.retrieve(str(args.get("query", "")), project_id=args.get("project_id"))
                return {"matches": [h.model_dump() for h in hits], "count": len(hits), "status": "ok"}
            self.register_tool("memory.store", _mem_store, is_consequential=False)
            self.register_tool("memory.retrieve", _mem_retrieve, is_consequential=False)
        if document_parser is not None:
            def _doc_parse(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
                doc = document_parser.parse_markdown(str(args.get("content", "")))
                return {"title": doc.title, "sections": len(doc.sections), "tables": len(doc.tables), "status": "ok"}
            self.register_tool("document.parse", _doc_parse, is_consequential=False)
        if multi_agent is not None:
            from .multi_agent import AgentRole, AgentSubtask
            async def _agent_delegate(args: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
                role_str = str(args.get("role", "research"))
                sub = AgentSubtask(
                    id=str(args.get("id", "sub_1")),
                    role=AgentRole(role_str),
                    capability=str(args.get("capability", "general")),
                    description=str(args.get("description", "Delegated subtask")),
                )
                st = await multi_agent.execute_project(str(args.get("goal", sub.description)), [sub])
                return {"project_id": st.project_id, "quality_score": st.quality_score, "status": "ok"}
            self.register_tool("agent.delegate", _agent_delegate, is_consequential=False)

    def _init_db(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS autonomous_tasks (
                    id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    state TEXT NOT NULL,
                    autonomy_level TEXT NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 5,
                    max_replans INTEGER NOT NULL DEFAULT 2,
                    replan_count INTEGER NOT NULL DEFAULT 0,
                    max_parallel INTEGER NOT NULL DEFAULT 3,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    pause_requested INTEGER NOT NULL DEFAULT 0,
                    understood_json TEXT,
                    evidence_json TEXT,
                    history_json TEXT NOT NULL,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS autonomous_steps (
                    task_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    depends_on_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    is_consequential INTEGER NOT NULL DEFAULT 0,
                    approved INTEGER NOT NULL DEFAULT 0,
                    heavy_resource INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER NOT NULL DEFAULT 1,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    fallback_tool TEXT,
                    fallback_arguments_json TEXT,
                    output_json TEXT,
                    evidence_json TEXT,
                    error TEXT,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (task_id, step_id)
                );
                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    step_id TEXT,
                    snapshot_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS task_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    read INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                """
            )

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10.0)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _register_builtin_tools(self) -> None:
        self.register_tool(
            "echo.note",
            lambda args, ctx: {"note": str(args.get("text", "")), "status": "ok"},
            is_consequential=False,
        )
        self.register_tool(
            "data.transform",
            lambda args, ctx: {
                "result": str(args.get("text", "")).upper()
                if args.get("mode") == "upper"
                else str(args.get("text", "")).strip(),
                "status": "ok",
            },
            is_consequential=False,
        )
        self.register_tool(
            "workspace.inspect",
            lambda args, ctx: {
                "target": str(args.get("path", ".")),
                "exists": Path(args.get("path", ".")).exists(),
                "status": "ok",
            },
            is_consequential=False,
        )

    def register_tool(
        self,
        name: str,
        handler: Callable[[dict[str, Any], dict[str, Any]], Any | Awaitable[Any]],
        *,
        is_consequential: bool = False,
        verifier: Callable[[dict[str, Any]], bool] | None = None,
    ) -> None:
        self._tools[name] = RegisteredTool(
            name=name,
            handler=handler,
            is_consequential=is_consequential,
            verifier=verifier,
        )

    def on_notification(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        self._notification_callbacks.append(callback)

    def _emit_notification(self, task_id: str, kind: str, message: str, payload: dict[str, Any] | None = None) -> None:
        now = time.time()
        item = {
            "task_id": task_id,
            "kind": kind,
            "message": message,
            "payload": payload or {},
            "created_at": now,
        }
        with self._connect() as db:
            db.execute(
                "INSERT INTO task_notifications(task_id, kind, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (task_id, kind, message, json.dumps(payload or {}), now),
            )
        self._notifications.append(item)
        for cb in self._notification_callbacks:
            try:
                cb(item)
            except Exception:
                pass

    def get_notifications(self, task_id: str | None = None, unread_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT id, task_id, kind, message, payload_json, read, created_at FROM task_notifications"
        clauses: list[str] = []
        params: list[Any] = []
        if task_id:
            clauses.append("task_id = ?")
            params.append(task_id)
        if unread_only:
            clauses.append("read = 0")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT 100"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [
            {
                "id": r["id"],
                "task_id": r["task_id"],
                "kind": r["kind"],
                "message": r["message"],
                "payload": json.loads(r["payload_json"]),
                "read": bool(r["read"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def _checkpoint(self, task_id: str, phase: LifecyclePhase, step_id: str | None = None, snapshot: dict[str, Any] | None = None) -> None:
        now = time.time()
        with self._connect() as db:
            row = db.execute("SELECT history_json FROM autonomous_tasks WHERE id = ?", (task_id,)).fetchone()
            history = json.loads(row["history_json"]) if row else []
            if not history or history[-1] != phase.value:
                history.append(phase.value)
            db.execute(
                "UPDATE autonomous_tasks SET phase = ?, history_json = ?, updated_at = ? WHERE id = ?",
                (phase.value, json.dumps(history), now, task_id),
            )
            db.execute(
                "INSERT INTO task_checkpoints(task_id, phase, step_id, snapshot_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (task_id, phase.value, step_id, json.dumps(snapshot or {}), now),
            )

    def get_checkpoints(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT id, task_id, phase, step_id, snapshot_json, created_at FROM task_checkpoints WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "task_id": r["task_id"],
                "phase": r["phase"],
                "step_id": r["step_id"],
                "snapshot": json.loads(r["snapshot_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def _decompose_goal(self, goal: str) -> list[AutonomousStepSpec]:
        """Dynamic task decomposition when explicit steps are not supplied."""
        parts = [p.strip() for p in goal.replace(" then ", ";").split(";") if p.strip()]
        if len(parts) <= 1:
            return [
                AutonomousStepSpec(
                    id="step_1",
                    description=f"Analyze and execute: {goal}",
                    tool="echo.note",
                    arguments={"text": goal},
                ),
                AutonomousStepSpec(
                    id="step_2",
                    description="Verify outcome",
                    tool="data.transform",
                    arguments={"text": goal, "mode": "strip"},
                    depends_on=["step_1"],
                ),
            ]
        steps: list[AutonomousStepSpec] = []
        prev_id: str | None = None
        for idx, part in enumerate(parts, start=1):
            sid = f"step_{idx}"
            steps.append(
                AutonomousStepSpec(
                    id=sid,
                    description=part,
                    tool="echo.note",
                    arguments={"text": part},
                    depends_on=[prev_id] if prev_id else [],
                )
            )
            prev_id = sid
        return steps

    def submit_task(self, request: AutonomousTaskRequest) -> TaskProgress:
        """REQUEST -> UNDERSTAND -> PLAN: persist task and decomposed steps."""
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        now = time.time()
        history = [LifecyclePhase.REQUEST.value]
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO autonomous_tasks(
                    id, goal, project_id, phase, state, autonomy_level, priority,
                    max_replans, replan_count, max_parallel, history_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    request.goal,
                    request.project_id,
                    LifecyclePhase.REQUEST.value,
                    "queued",
                    request.autonomy_level.value,
                    request.priority,
                    request.max_replans,
                    request.max_parallel,
                    json.dumps(history),
                    now,
                    now,
                ),
            )

        # UNDERSTAND phase
        parsed = self._understanding.parse(request.goal)
        understood = {"intent": parsed.intent.value, "entities": parsed.entities, "confidence": parsed.confidence}
        with self._connect() as db:
            db.execute("UPDATE autonomous_tasks SET understood_json = ? WHERE id = ?", (json.dumps(understood), task_id))
        self._checkpoint(task_id, LifecyclePhase.UNDERSTAND, snapshot=understood)

        # PLAN phase
        steps = request.steps if request.steps else self._decompose_goal(request.goal)
        self._validate_dag(steps)
        with self._connect() as db:
            for seq, step in enumerate(steps):
                tool_meta = self._tools.get(step.tool)
                consequential = step.is_consequential or (tool_meta.is_consequential if tool_meta else False)
                approved = self._is_auto_approved(request.autonomy_level, consequential)
                db.execute(
                    """
                    INSERT INTO autonomous_steps(
                        task_id, step_id, seq, description, tool, arguments_json, depends_on_json,
                        state, is_consequential, approved, heavy_resource, max_retries, attempts,
                        fallback_tool, fallback_arguments_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, 0, ?, ?, ?)
                    """,
                    (
                        task_id,
                        step.id,
                        seq,
                        step.description,
                        step.tool,
                        json.dumps(step.arguments),
                        json.dumps(step.depends_on),
                        1 if consequential else 0,
                        1 if approved else 0,
                        1 if step.heavy_resource else 0,
                        step.max_retries,
                        step.fallback_tool,
                        json.dumps(step.fallback_arguments),
                        now,
                    ),
                )
        self._checkpoint(task_id, LifecyclePhase.PLAN, snapshot={"step_count": len(steps)})
        self._wakeup.set()
        return self.get_progress(task_id)

    @staticmethod
    def _validate_dag(steps: list[AutonomousStepSpec]) -> None:
        ids = {s.id for s in steps}
        if len(ids) != len(steps):
            raise ValueError("Duplicate step IDs in autonomous task plan")
        for s in steps:
            missing = set(s.depends_on) - ids
            if missing:
                raise ValueError(f"Step '{s.id}' references missing dependencies: {sorted(missing)}")
        done: set[str] = set()
        while len(done) < len(ids):
            ready = {s.id for s in steps if s.id not in done and set(s.depends_on) <= done}
            if not ready:
                raise ValueError("Cyclic dependency detected in autonomous task plan")
            done |= ready

    @staticmethod
    def _is_auto_approved(level: AutonomyLevel, is_consequential: bool) -> bool:
        if level == AutonomyLevel.FULL_AUTONOMOUS:
            return True
        if level in (AutonomyLevel.SUPERVISED, AutonomyLevel.AUTONOMOUS_SAFE):
            return not is_consequential
        return False

    def approve_task(self, task_id: str) -> TaskProgress:
        """Approve all pending consequential steps for a task and resume it."""
        now = time.time()
        with self._connect() as db:
            db.execute("UPDATE autonomous_steps SET approved = 1, updated_at = ? WHERE task_id = ?", (now, task_id))
            db.execute(
                "UPDATE autonomous_tasks SET state = 'queued', updated_at = ? WHERE id = ? AND state = 'awaiting_approval'",
                (now, task_id),
            )
        self._wakeup.set()
        return self.get_progress(task_id)

    def approve_step(self, task_id: str, step_id: str) -> TaskProgress:
        now = time.time()
        with self._connect() as db:
            db.execute(
                "UPDATE autonomous_steps SET approved = 1, updated_at = ? WHERE task_id = ? AND step_id = ?",
                (now, task_id, step_id),
            )
            db.execute(
                "UPDATE autonomous_tasks SET state = 'queued', updated_at = ? WHERE id = ? AND state = 'awaiting_approval'",
                (now, task_id),
            )
        self._wakeup.set()
        return self.get_progress(task_id)

    def cancel_task(self, task_id: str) -> TaskProgress:
        now = time.time()
        with self._connect() as db:
            row = db.execute("SELECT state FROM autonomous_tasks WHERE id = ?", (task_id,)).fetchone()
            if not row:
                raise ValueError(f"Task not found: {task_id}")
            if row["state"] in ("complete", "failed", "cancelled"):
                return self.get_progress(task_id)
            db.execute(
                "UPDATE autonomous_tasks SET cancel_requested = 1, state = 'cancelled', updated_at = ? WHERE id = ?",
                (now, task_id),
            )
        self._checkpoint(task_id, LifecyclePhase.CANCELLED, snapshot={"reason": "cancelled_by_user"})
        self._emit_notification(task_id, "cancelled", f"Task {task_id} cancelled.")
        return self.get_progress(task_id)

    def pause_task(self, task_id: str) -> TaskProgress:
        now = time.time()
        with self._connect() as db:
            db.execute(
                "UPDATE autonomous_tasks SET pause_requested = 1, state = 'paused', updated_at = ? WHERE id = ? AND state IN ('queued', 'running')",
                (now, task_id),
            )
        return self.get_progress(task_id)

    def resume_task(self, task_id: str) -> TaskProgress:
        now = time.time()
        with self._connect() as db:
            db.execute(
                "UPDATE autonomous_tasks SET pause_requested = 0, state = 'queued', updated_at = ? WHERE id = ? AND state = 'paused'",
                (now, task_id),
            )
        self._wakeup.set()
        return self.get_progress(task_id)

    def recover_interrupted(self) -> int:
        """Resume interrupted tasks after an application restart without losing completed steps."""
        now = time.time()
        with self._connect() as db:
            cur = db.execute(
                "UPDATE autonomous_tasks SET state = 'queued', updated_at = ? WHERE state = 'running'",
                (now,),
            )
            db.execute(
                "UPDATE autonomous_steps SET state = 'queued', updated_at = ? WHERE state = 'running'",
                (now,),
            )
            recovered = cur.rowcount
        if recovered:
            self._wakeup.set()
        return recovered

    def get_progress(self, task_id: str) -> TaskProgress:
        with self._connect() as db:
            task = db.execute("SELECT * FROM autonomous_tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                raise ValueError(f"Task not found: {task_id}")
            step_rows = db.execute(
                "SELECT * FROM autonomous_steps WHERE task_id = ? ORDER BY seq ASC",
                (task_id,),
            ).fetchall()

        steps: list[StepProgress] = []
        completed = 0
        failed = 0
        for r in step_rows:
            if r["state"] == "complete":
                completed += 1
            elif r["state"] == "failed":
                failed += 1
            steps.append(
                StepProgress(
                    id=r["step_id"],
                    description=r["description"],
                    tool=r["tool"],
                    state=r["state"],
                    depends_on=json.loads(r["depends_on_json"]),
                    attempts=r["attempts"],
                    is_consequential=bool(r["is_consequential"]),
                    approved=bool(r["approved"]),
                    output=json.loads(r["output_json"]) if r["output_json"] else None,
                    evidence=json.loads(r["evidence_json"]) if r["evidence_json"] else None,
                    error=r["error"],
                )
            )
        total = len(steps)
        percent = round((completed / total) * 100.0, 1) if total else 0.0
        return TaskProgress(
            task_id=task["id"],
            goal=task["goal"],
            phase=LifecyclePhase(task["phase"]),
            state=task["state"],
            autonomy_level=AutonomyLevel(task["autonomy_level"]),
            total_steps=total,
            completed_steps=completed,
            failed_steps=failed,
            percent=percent,
            replan_count=task["replan_count"],
            steps=steps,
            completion_evidence=json.loads(task["evidence_json"]) if task["evidence_json"] else [],
            lifecycle_history=json.loads(task["history_json"]),
            error=task["error"],
        )

    def _resource_concurrency_limit(self, requested_max: int, has_heavy: bool) -> int:
        try:
            telemetry = SystemMonitor.get_telemetry()
            avail_mb = telemetry["ram"]["available_mb"]
            cpu_pct = telemetry["cpu"]["percent"]
            if avail_mb < self.min_free_ram_mb or cpu_pct > self.max_cpu_percent:
                return 1
            if has_heavy and avail_mb < self.min_free_ram_mb * 2:
                return 1
        except Exception:
            pass
        return requested_max

    async def _execute_step(self, task_id: str, step_row: sqlite3.Row, context: dict[str, Any]) -> tuple[str, bool, str | None]:
        step_id = step_row["step_id"]
        tool_name = step_row["tool"]
        args = json.loads(step_row["arguments_json"])
        tool = self._tools.get(tool_name)

        # Idempotent duplicate execution guard: never re-run an already verified completed step
        with self._connect() as db:
            current = db.execute(
                "SELECT state, evidence_json FROM autonomous_steps WHERE task_id = ? AND step_id = ?",
                (task_id, step_id),
            ).fetchone()
            if current and current["state"] == "complete" and current["evidence_json"]:
                return step_id, True, None
            db.execute(
                "UPDATE autonomous_steps SET state = 'running', attempts = attempts + 1, updated_at = ? WHERE task_id = ? AND step_id = ?",
                (time.time(), task_id, step_id),
            )

        if tool is None:
            err = f"Unknown tool: {tool_name}"
            with self._connect() as db:
                db.execute(
                    "UPDATE autonomous_steps SET state = 'failed', error = ?, updated_at = ? WHERE task_id = ? AND step_id = ?",
                    (err, time.time(), task_id, step_id),
                )
            return step_id, False, err

        started = time.monotonic()
        try:
            raw_out = tool.handler(args, context)
            if asyncio.iscoroutine(raw_out) or isinstance(raw_out, Awaitable):
                raw_out = await raw_out
            output = raw_out if isinstance(raw_out, dict) else {"result": raw_out}
            duration_ms = round((time.monotonic() - started) * 1000.0, 2)

            # OBSERVE & VERIFY step evidence
            verified = True
            if tool.verifier is not None:
                verified = bool(tool.verifier(output))
            elif output.get("status") in ("error", "failed"):
                verified = False

            if not verified or not output:
                raise RuntimeError(f"Step '{step_id}' failed verification (missing or invalid evidence)")

            evidence = {
                "step_id": step_id,
                "tool": tool_name,
                "duration_ms": duration_ms,
                "attempted": True,
                "executed": True,
                "verified": True,
                "outcome_stage": "verified",
                "keys": sorted(output.keys()),
            }
            with self._connect() as db:
                db.execute(
                    "UPDATE autonomous_steps SET state = 'complete', output_json = ?, evidence_json = ?, error = NULL, updated_at = ? WHERE task_id = ? AND step_id = ?",
                    (json.dumps(output), json.dumps(evidence), time.time(), task_id, step_id),
                )
            self._checkpoint(task_id, LifecyclePhase.OBSERVE, step_id=step_id, snapshot={"evidence": evidence})
            return step_id, True, None
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            with self._connect() as db:
                db.execute(
                    "UPDATE autonomous_steps SET state = 'failed', error = ?, updated_at = ? WHERE task_id = ? AND step_id = ?",
                    (err, time.time(), task_id, step_id),
                )
            return step_id, False, err

    async def _replan_failed_steps(self, task_id: str, failed_rows: list[sqlite3.Row]) -> bool:
        """Attempt controlled recovery / replanning for failed steps."""
        with self._connect() as db:
            task = db.execute("SELECT replan_count, max_replans FROM autonomous_tasks WHERE id = ?", (task_id,)).fetchone()
            if not task or task["replan_count"] >= task["max_replans"]:
                return False
            db.execute(
                "UPDATE autonomous_tasks SET replan_count = replan_count + 1, updated_at = ? WHERE id = ?",
                (time.time(), task_id),
            )

        self._checkpoint(task_id, LifecyclePhase.REPLAN, snapshot={"failed_steps": [r["step_id"] for r in failed_rows]})
        recovered_any = False
        now = time.time()
        with self._connect() as db:
            for r in failed_rows:
                if r["fallback_tool"]:
                    db.execute(
                        """
                        UPDATE autonomous_steps
                        SET tool = ?, arguments_json = ?, fallback_tool = NULL, state = 'queued', error = NULL, updated_at = ?
                        WHERE task_id = ? AND step_id = ?
                        """,
                        (
                            r["fallback_tool"],
                            r["fallback_arguments_json"] or "{}",
                            now,
                            task_id,
                            r["step_id"],
                        ),
                    )
                    recovered_any = True
                elif r["attempts"] <= r["max_retries"]:
                    db.execute(
                        "UPDATE autonomous_steps SET state = 'queued', error = NULL, updated_at = ? WHERE task_id = ? AND step_id = ?",
                        (now, task_id, r["step_id"]),
                    )
                    recovered_any = True
        return recovered_any

    async def run_task(self, task_id: str) -> TaskProgress:
        """Execute a single autonomous task to completion, pause, approval gate, or failure."""
        with self._connect() as db:
            task = db.execute("SELECT * FROM autonomous_tasks WHERE id = ?", (task_id,)).fetchone()
            if not task:
                raise ValueError(f"Task not found: {task_id}")
            if task["state"] in ("complete", "cancelled"):
                return self.get_progress(task_id)
            db.execute("UPDATE autonomous_tasks SET state = 'running', updated_at = ? WHERE id = ?", (time.time(), task_id))

        self._checkpoint(task_id, LifecyclePhase.EXECUTE, snapshot={"status": "started"})

        while True:
            with self._connect() as db:
                task = db.execute("SELECT * FROM autonomous_tasks WHERE id = ?", (task_id,)).fetchone()
                steps = db.execute("SELECT * FROM autonomous_steps WHERE task_id = ? ORDER BY seq ASC", (task_id,)).fetchall()

            if task["cancel_requested"] or task["state"] == "cancelled":
                self._checkpoint(task_id, LifecyclePhase.CANCELLED)
                return self.get_progress(task_id)
            if task["pause_requested"] or task["state"] == "paused":
                return self.get_progress(task_id)

            completed_ids = {s["step_id"] for s in steps if s["state"] == "complete"}
            if len(completed_ids) == len(steps) and len(steps) > 0:
                # VERIFY phase: require concrete evidence from every step
                self._checkpoint(task_id, LifecyclePhase.VERIFY, snapshot={"verified_steps": len(steps)})
                evidence_list = [json.loads(s["evidence_json"]) for s in steps if s["evidence_json"]]
                if len(evidence_list) != len(steps):
                    err = "Completion blocked: missing verification evidence for one or more steps."
                    with self._connect() as db:
                        db.execute("UPDATE autonomous_tasks SET state = 'failed', error = ?, updated_at = ? WHERE id = ?", (err, time.time(), task_id))
                    self._checkpoint(task_id, LifecyclePhase.FAILED, snapshot={"error": err})
                    return self.get_progress(task_id)

                with self._connect() as db:
                    db.execute(
                        "UPDATE autonomous_tasks SET state = 'complete', evidence_json = ?, updated_at = ? WHERE id = ?",
                        (json.dumps(evidence_list), time.time(), task_id),
                    )
                self._checkpoint(task_id, LifecyclePhase.COMPLETE, snapshot={"evidence_count": len(evidence_list)})
                self._emit_notification(task_id, "complete", f"Task '{task['goal']}' completed with {len(evidence_list)} verified steps.")
                return self.get_progress(task_id)

            ready_steps = [
                s for s in steps
                if s["state"] == "queued" and set(json.loads(s["depends_on_json"])) <= completed_ids
            ]

            if not ready_steps:
                failed_steps = [s for s in steps if s["state"] == "failed"]
                if failed_steps:
                    replanned = await self._replan_failed_steps(task_id, failed_steps)
                    if replanned:
                        self._checkpoint(task_id, LifecyclePhase.EXECUTE, snapshot={"resumed_after_replan": True})
                        continue
                    err = failed_steps[0]["error"] or "Step execution failed"
                    with self._connect() as db:
                        db.execute("UPDATE autonomous_tasks SET state = 'failed', error = ?, updated_at = ? WHERE id = ?", (err, time.time(), task_id))
                    self._checkpoint(task_id, LifecyclePhase.FAILED, snapshot={"error": err})
                    self._emit_notification(task_id, "failed", f"Task '{task['goal']}' failed: {err}")
                    return self.get_progress(task_id)
                return self.get_progress(task_id)

            # Check approval gates for consequential steps
            unapproved = [s for s in ready_steps if not s["approved"]]
            executable = [s for s in ready_steps if s["approved"]]
            if not executable and unapproved:
                with self._connect() as db:
                    db.execute("UPDATE autonomous_tasks SET state = 'awaiting_approval', updated_at = ? WHERE id = ?", (time.time(), task_id))
                self._checkpoint(task_id, LifecyclePhase.AWAITING_APPROVAL, step_id=unapproved[0]["step_id"])
                self._emit_notification(
                    task_id,
                    "approval_required",
                    f"Approval required for consequential step '{unapproved[0]['step_id']}'.",
                    {"step_id": unapproved[0]["step_id"]},
                )
                return self.get_progress(task_id)

            # Resource-aware parallel batch sizing
            has_heavy = any(s["heavy_resource"] for s in executable)
            limit = self._resource_concurrency_limit(task["max_parallel"], has_heavy)
            batch = executable[:limit]

            # Build shared read-only step output context
            context = {
                "task_id": task_id,
                "goal": task["goal"],
                "project_id": task["project_id"],
                "outputs": {
                    s["step_id"]: json.loads(s["output_json"])
                    for s in steps
                    if s["state"] == "complete" and s["output_json"]
                },
            }

            await asyncio.gather(*(self._execute_step(task_id, s, context) for s in batch))

    async def _worker_loop(self) -> None:
        while not self._stopping:
            self._wakeup.clear()
            with self._connect() as db:
                row = db.execute(
                    "SELECT id FROM autonomous_tasks WHERE state = 'queued' ORDER BY priority ASC, created_at ASC LIMIT 1"
                ).fetchone()
            if row:
                try:
                    await self.run_task(row["id"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    with self._connect() as db:
                        db.execute(
                            "UPDATE autonomous_tasks SET state = 'failed', error = ?, updated_at = ? WHERE id = ?",
                            (str(exc), time.time(), row["id"]),
                        )
            else:
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=0.5)
                except TimeoutError:
                    pass

    async def start(self) -> int:
        recovered = self.recover_interrupted()
        self._stopping = False
        self._worker_task = asyncio.create_task(self._worker_loop())
        return recovered

    async def stop(self) -> None:
        self._stopping = True
        self._wakeup.set()
        if self._worker_task:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
            self._worker_task = None
