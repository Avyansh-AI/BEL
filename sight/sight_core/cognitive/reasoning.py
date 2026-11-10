"""BEL Reasoning Engine.

Breaks complex problems into smaller problems, identifies dependencies,
evaluates alternative execution approaches, quantifies uncertainty, and
generates structured reasoning traces.
"""
from __future__ import annotations

import re
from typing import Any
from pydantic import Field
from ..tools import StrictModel


class SubProblem(StrictModel):
    id: str
    description: str
    dependencies: list[str] = Field(default_factory=list)
    candidate_approaches: list[str] = Field(default_factory=list)
    selected_approach: str = ""
    estimated_risk: str = "low"


class ReasoningTrace(StrictModel):
    premise: str
    sub_problems: list[SubProblem] = Field(default_factory=list)
    trade_offs: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    recommended_strategy: str
    confidence: float = Field(ge=0.0, le=1.0)


class ReasoningEngine:
    """Structured analytical reasoning and problem decomposition engine."""

    def reason_about_task(
        self,
        goal: str,
        sub_instructions: list[str] | None = None,
        entities: dict[str, Any] | None = None,
    ) -> ReasoningTrace:
        """Analyze a goal, decompose into sub-problems, and generate a reasoning trace."""
        entities = entities or {}
        sub_instructions = sub_instructions or [goal]

        sub_problems: list[SubProblem] = []
        trade_offs: list[str] = []
        uncertainties: list[str] = []

        # If multiple instructions were identified, decompose directly
        if len(sub_instructions) > 1:
            for idx, instr in enumerate(sub_instructions, start=1):
                prob_id = f"sub-{idx}"
                deps = [f"sub-{idx-1}"] if idx > 1 else []
                approaches = self._identify_approaches(instr)
                sub_problems.append(
                    SubProblem(
                        id=prob_id,
                        description=instr,
                        dependencies=deps,
                        candidate_approaches=approaches,
                        selected_approach=approaches[0] if approaches else "execute_directly",
                        estimated_risk=self._estimate_risk(instr),
                    )
                )
            trade_offs.append("Sequential execution ensures step dependencies are verified before subsequent steps run.")
        else:
            # Single instruction: analyze complexity
            approaches = self._identify_approaches(goal)
            sub_problems.append(
                SubProblem(
                    id="sub-1",
                    description=goal,
                    dependencies=[],
                    candidate_approaches=approaches,
                    selected_approach=approaches[0] if approaches else "execute_directly",
                    estimated_risk=self._estimate_risk(goal),
                )
            )

        # Check for uncertainty factors
        if "delete" in goal.lower() or "remove" in goal.lower():
            uncertainties.append("Destructive operation requires explicit confirmation of preimage or exact target.")
        if entities.get("anaphoric_resolved"):
            uncertainties.append(f"Target entity was resolved from recent context as '{entities.get('primary_file')}'.")

        confidence = 0.95 if not uncertainties else 0.85
        strategy = (
            f"Execute {len(sub_problems)} ordered steps using verified local tools and fail-closed state validation."
        )

        return ReasoningTrace(
            premise=goal,
            sub_problems=sub_problems,
            trade_offs=trade_offs,
            uncertainties=uncertainties,
            recommended_strategy=strategy,
            confidence=confidence,
        )

    def _identify_approaches(self, text: str) -> list[str]:
        low = text.lower()
        if "notepad" in low or "calculator" in low:
            return ["launch_via_windows_broker", "verify_foreground_window"]
        if "file" in low or any(ext in low for ext in (".txt", ".md", ".json", ".py", ".docx")):
            if "edit" in low or "change" in low:
                return ["read_preimage_hash", "acquire_exclusive_win32_handle", "atomic_write_and_verify"]
            if "create" in low or "write" in low:
                return ["verify_destination_absent", "write_new_with_preimage_journal", "verify_sha256"]
            if "undo" in low:
                return ["locate_latest_verified_undo_id", "restore_preimage"]
            return ["query_private_workspace"]
        return ["direct_response_heuristic", "local_gemma_synthesis"]

    def _estimate_risk(self, text: str) -> str:
        low = text.lower()
        if any(w in low for w in ("delete", "remove", "clear", "format", "truncate")):
            return "high"
        if any(w in low for w in ("edit", "change", "write", "rename", "create")):
            return "medium"
        return "low"
