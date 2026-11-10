"""BEL Response Engine.

Formats execution outputs and conversational replies in BEL's signature MCU
J.A.R.V.I.S.-inspired persona. Ensures truth-in-reporting, non-repetitive phrasing,
and transparent failure explanations.
"""
from __future__ import annotations

import random
from typing import Any
from ..tools import StrictModel


class ResponseEngine:
    """Formats verified outcomes and assistant replies with MCU J.A.R.V.I.S. demeanor."""

    ACK_PREFIXES = (
        "Right away, sir.",
        "Very well, sir.",
        "Understood, sir.",
        "Certainly, sir.",
        "At your service, sir.",
    )

    COMPLETION_PHRASES = (
        "Operation completed successfully.",
        "All requested parameters have been verified.",
        "Task completed and state validated.",
        "Done, sir. The system state has been confirmed.",
    )

    def format_plan_proposal(self, plan_goal: str, steps_count: int, steps_summary: list[str]) -> str:
        """Format an execution proposal requiring human authorization."""
        prefix = self._pick_ack()
        step_lines = "\n".join(f"  {idx}. {desc}" for idx, desc in enumerate(steps_summary, start=1))
        return (
            f"{prefix} I have formulated a {steps_count}-step plan to {plan_goal.rstrip('.')}:\n"
            f"{step_lines}\n\n"
            "Please review and authorize execution when ready."
        )

    def format_tool_result(self, tool_name: str, result: dict[str, Any]) -> str:
        """Format a verified tool execution result with evidence."""
        status = result.get("status", "done")
        evidence = result.get("evidence", {})

        if status == "done":
            if tool_name == "files.create":
                name = evidence.get("name", "file")
                undo_id = evidence.get("undo_id", "")
                sha_prefix = evidence.get("sha256", "")[:8]
                return f"File '{name}' has been created (SHA256: {sha_prefix}...). A reversible pre-image journal was recorded (Undo ID: {undo_id[:8]}...)."

            if tool_name == "files.edit":
                name = evidence.get("name", "file")
                undo_id = evidence.get("undo_id", "")
                return f"File '{name}' has been modified and verified. Previous content preserved in local journal (Undo ID: {undo_id[:8]}...)."

            if tool_name == "files.undo":
                return "The requested modification has been reversed. Original file state is restored."

            if tool_name == "app.launch":
                app = evidence.get("application", "application")
                pid = evidence.get("pid", "unknown")
                return f"{app.capitalize()} is running and focused in the foreground (PID: {pid})."

            if tool_name == "files.list":
                names = evidence.get("names", [])
                if not names:
                    return "The private workspace is currently empty."
                return f"Found {len(names)} item(s) in workspace: " + ", ".join(names[:10])

            return f"Action '{tool_name}' completed. Evidence verified."

        if status == "unverified":
            reason = evidence.get("reason", "Verification could not be confirmed.")
            return f"Notice: Action '{tool_name}' could not be cryptographically verified: {reason}"

        reason = evidence.get("reason", "An unexpected error occurred during execution.")
        return f"Execution failed for '{tool_name}': {reason}"

    def format_failure(self, operation: str, reason: str, recovery_hint: str | None = None) -> str:
        """Transparently explain an operational or safety failure."""
        hint = f" Recommendation: {recovery_hint}" if recovery_hint else ""
        return f"I was unable to complete {operation}. {reason}{hint}"

    def format_clarification_prompt(self, question: str) -> str:
        """Prompt user for missing details."""
        return f"Before I proceed, sir: {question}"

    def _pick_ack(self) -> str:
        return random.choice(self.ACK_PREFIXES)
