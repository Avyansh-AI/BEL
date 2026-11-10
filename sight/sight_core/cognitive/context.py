"""BEL Context Manager.

Maintains conversation state, tracks ongoing multi-step tasks, preserves
entity bindings, resolves pronouns/anaphora, and manages context windows.
"""
from __future__ import annotations

import time
from typing import Any, Literal
from pydantic import Field
from ..tools import StrictModel


class TaskState(StrictModel):
    task_id: str
    goal: str
    status: Literal["pending", "running", "completed", "failed", "paused"] = "pending"
    plan_id: str | None = None
    current_step_index: int = 0
    total_steps: int = 1
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class TurnRecord(StrictModel):
    role: Literal["user", "assistant", "system"]
    text: str
    timestamp: float = Field(default_factory=time.time)
    intent: str | None = None
    entities: dict[str, Any] = Field(default_factory=dict)


class ContextManager:
    """Manages conversational continuity, ongoing task lifecycles, and entity memory."""

    def __init__(self, max_history_turns: int = 50) -> None:
        self.max_history_turns = max_history_turns
        self.turns: list[TurnRecord] = []
        self.active_entities: dict[str, Any] = {}
        self.ongoing_tasks: dict[str, TaskState] = {}
        self.active_task_id: str | None = None
        self.pending_clarification: str | None = None

    def add_turn(
        self,
        role: Literal["user", "assistant", "system"],
        text: str,
        intent: str | None = None,
        entities: dict[str, Any] | None = None,
    ) -> TurnRecord:
        """Record a conversational turn and update active entity bindings."""
        entities = entities or {}
        record = TurnRecord(
            role=role,
            text=text,
            timestamp=time.time(),
            intent=intent,
            entities=entities,
        )
        self.turns.append(record)

        # Update working entity memory
        if "files" in entities and entities["files"]:
            self.active_entities["primary_file"] = entities["files"][-1]
            self.active_entities["recent_files"] = entities["files"]
        if "application" in entities and entities["application"]:
            self.active_entities["last_application"] = entities["application"]
        if "tool" in entities:
            self.active_entities["last_tool"] = entities["tool"]

        # Keep turns bounded
        if len(self.turns) > self.max_history_turns:
            self.turns = self.turns[-self.max_history_turns:]

        return record

    def resolve_references(self, text: str) -> dict[str, Any]:
        """Resolve pronouns and anaphoric references from working memory."""
        resolved: dict[str, Any] = {}
        low = text.lower()

        # Check for file references: "that file", "the file", "it"
        if any(term in low for term in ("that file", "the file", "this file", "it")):
            if "primary_file" in self.active_entities:
                resolved["primary_file"] = self.active_entities["primary_file"]
                resolved["file_resolved"] = True

        # Check for application references: "the app", "that app"
        if any(term in low for term in ("the app", "that app", "it")):
            if "last_application" in self.active_entities:
                resolved["application"] = self.active_entities["last_application"]
                resolved["app_resolved"] = True

        return resolved

    def track_task(self, task_id: str, goal: str, total_steps: int = 1) -> TaskState:
        """Register a new ongoing task."""
        state = TaskState(task_id=task_id, goal=goal, total_steps=total_steps, status="running")
        self.ongoing_tasks[task_id] = state
        self.active_task_id = task_id
        return state

    def update_task(
        self,
        task_id: str,
        status: Literal["pending", "running", "completed", "failed", "paused"],
        step_index: int | None = None,
    ) -> TaskState | None:
        """Update the progress of an ongoing task."""
        task = self.ongoing_tasks.get(task_id)
        if not task:
            return None
        task.status = status
        task.updated_at = time.time()
        if step_index is not None:
            task.current_step_index = step_index
        if status in {"completed", "failed"} and self.active_task_id == task_id:
            self.active_task_id = None
        return task

    def get_active_task(self) -> TaskState | None:
        """Retrieve the currently executing task if any."""
        if self.active_task_id:
            return self.ongoing_tasks.get(self.active_task_id)
        return None

    def get_recent_context_text(self, max_turns: int = 6) -> str:
        """Format recent turns into a context snippet for inference."""
        slice_turns = self.turns[-max_turns:] if self.turns else []
        lines = []
        for turn in slice_turns:
            lines.append(f"{turn.role.capitalize()}: {turn.text}")
        return "\n".join(lines)


ConversationContext = ContextManager
