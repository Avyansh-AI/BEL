"""BEL Planning Engine.

Converts reasoning objectives into actionable, ordered plan steps with
explicit dependencies, tracks progress, and performs dynamic replanning
when conditions or step outcomes change.
"""
from __future__ import annotations

from enum import Enum
import time
import uuid
from typing import Any
from pydantic import Field
from ..tools import StrictModel
from .reasoning import ReasoningTrace, SubProblem


class StepStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class PlanStep(StrictModel):
    id: str
    description: str
    tool: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: dict[str, Any] | None = None
    is_consequential: bool = False
    requires_approval: bool = False


class Plan(StrictModel):
    plan_id: str = Field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:8]}")
    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    status: str = "active"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def is_completed(self) -> bool:
        return all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in self.steps)

    def has_failures(self) -> bool:
        return any(s.status == StepStatus.FAILED for s in self.steps)


class PlanningEngine:
    """Orchestrates structured, dependency-aware execution plans."""

    def create_plan(
        self,
        trace: ReasoningTrace,
        entities: dict[str, Any] | None = None,
    ) -> Plan:
        """Translate a reasoning trace into an actionable execution plan."""
        entities = entities or {}
        steps: list[PlanStep] = []

        for sub in trace.sub_problems:
            tool, args, requires_approval, consequential = self._resolve_tool_call(sub.description, entities)
            status = StepStatus.READY if not sub.dependencies else StepStatus.PENDING
            steps.append(
                PlanStep(
                    id=sub.id,
                    description=sub.description,
                    tool=tool,
                    arguments=args,
                    dependencies=sub.dependencies,
                    status=status,
                    requires_approval=requires_approval,
                    is_consequential=consequential,
                )
            )

        return Plan(goal=trace.premise, steps=steps)

    def get_ready_steps(self, plan: Plan) -> list[PlanStep]:
        """Return steps that are ready for immediate execution."""
        completed_ids = {s.id for s in plan.steps if s.status == StepStatus.COMPLETED}
        ready: list[PlanStep] = []

        for step in plan.steps:
            if step.status in (StepStatus.PENDING, StepStatus.READY):
                if all(dep in completed_ids for dep in step.dependencies):
                    step.status = StepStatus.READY
                    ready.append(step)

        return ready

    def mark_step(
        self,
        plan: Plan,
        step_id: str,
        status: StepStatus,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Record step execution result and update plan lifecycle."""
        for step in plan.steps:
            if step.id == step_id:
                step.status = status
                step.result = result
                plan.updated_at = time.time()
                break

        if plan.is_completed():
            plan.status = "completed"
        elif plan.has_failures():
            plan.status = "failed"

    def replan_on_failure(
        self,
        plan: Plan,
        failed_step_id: str,
        error_reason: str,
    ) -> Plan:
        """Dynamically adapt remaining plan steps upon a step failure."""
        plan.updated_at = time.time()
        for step in plan.steps:
            if step.id == failed_step_id:
                step.status = StepStatus.FAILED
                step.result = {"error": error_reason}
            elif failed_step_id in step.dependencies and step.status == StepStatus.PENDING:
                # Cancel or pause downstream dependents
                step.status = StepStatus.CANCELLED
                step.result = {"reason": f"Dependent step '{failed_step_id}' failed: {error_reason}"}

        plan.status = "partially_failed"
        return plan

    def _resolve_tool_call(
        self, text: str, entities: dict[str, Any]
    ) -> tuple[str | None, dict[str, Any], bool, bool]:
        low = text.lower()

        # Notepad / Calculator
        if "notepad" in low:
            return "app.launch", {"application": "notepad"}, True, False
        if "calculator" in low or "calc" in low:
            return "app.launch", {"application": "calculator"}, True, False

        # File creation
        if any(w in low for w in ("create file", "create a file", "write a file", "new file")):
            filename = entities.get("primary_file", "output.txt")
            return "files.create", {"name": filename, "content": f"Generated content for {filename}"}, True, False

        # File undo
        if "undo" in low:
            return "files.undo", {"undo_id": entities.get("undo_id", "")}, True, False

        # File list
        if "list" in low and ("files" in low or "directory" in low):
            return "files.list", {}, False, False

        # Markdown Document
        if "markdown" in low or "doc" in low or "summary report" in low:
            return "documents.markdown", {"title": "Summary", "text": "Executive summary report."}, True, False

        # General non-tool conversational or analytical step
        return None, {}, False, False
