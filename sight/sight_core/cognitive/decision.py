"""BEL Decision Engine.

Evaluates execution risks, enforces strict permission boundaries, and performs
task-aware model and tool selection across local and cloud providers.
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import Field
from ..tools import StrictModel


class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    REVERSIBLE = "reversible"
    DESTRUCTIVE = "destructive"
    EXTERNAL_COMMUNICATION = "external_communication"
    CONSEQUENTIAL = "consequential"


class ActionPermission(StrictModel):
    level: RiskLevel
    requires_human_approval: bool
    reason: str
    reversible: bool = False
    audit_category: str = "operational"


class ModelRoute(StrictModel):
    provider: str
    model_name: str
    task_category: str
    cost_tier: str = "free"
    reasoning_depth: str = "standard"
    rationale: str


class DecisionEngine:
    """Evaluates task risks, human authorization requirements, and model routing."""

    DEFAULT_MODELS = {
        "local": "gemma4:e4b-it-qat",
        "groq_conversation": "qwen-2.5-32b",
        "groq_coding": "qwen-2.5-coder-32b",
        "tokenharbor_reasoning": "deepseek-reasoner",
        "tokenharbor_general": "deepseek-chat",
        "gemini_vision": "gemini-2.0-flash",
        "gemini_reasoning": "gemini-2.0-flash-thinking-exp",
        "openrouter_default": "meta-llama/llama-3.2-3b-instruct:free",
    }

    def evaluate_permission(self, tool_name: str, arguments: dict[str, Any] | None = None) -> ActionPermission:
        """Classify tool risk level and determine if human grant is required."""
        arguments = arguments or {}

        # 1. Read-only tools: safe for automated execution
        if tool_name in {"files.list", "files.search", "system.telemetry", "health", "status", "memory.search"}:
            return ActionPermission(
                level=RiskLevel.READ_ONLY,
                requires_human_approval=False,
                reason="Read-only operation within private workspace; no side effects.",
                reversible=True,
            )

        # 2. Reversible file operations: requires approval, journaled pre-image
        if tool_name in {"files.create", "files.edit", "files.rename", "files.undo"}:
            return ActionPermission(
                level=RiskLevel.REVERSIBLE,
                requires_human_approval=True,
                reason="Mutates host workspace files; protected by cryptographic pre-image journal.",
                reversible=True,
            )

        # 3. Application launchers: external OS presentation
        if tool_name == "app.launch":
            app = arguments.get("application", "unknown")
            return ActionPermission(
                level=RiskLevel.CONSEQUENTIAL,
                requires_human_approval=True,
                reason=f"Launches external OS GUI application ({app}); requires single-use user grant.",
                reversible=False,
            )

        # 4. Destructive / purge actions
        if tool_name in {"history.clear", "files.delete", "memory.purge"}:
            return ActionPermission(
                level=RiskLevel.DESTRUCTIVE,
                requires_human_approval=True,
                reason="Permanent state modification or deletion; irreversible.",
                reversible=False,
            )

        # 5. External communications / cloud actions
        if "cloud" in tool_name or "network" in tool_name or "email" in tool_name:
            return ActionPermission(
                level=RiskLevel.EXTERNAL_COMMUNICATION,
                requires_human_approval=True,
                reason="Transmits data outside local host boundary.",
                reversible=False,
            )

        # Default fail-closed
        return ActionPermission(
            level=RiskLevel.CONSEQUENTIAL,
            requires_human_approval=True,
            reason="Unclassified capability; default fail-closed human authorization mandatory.",
            reversible=False,
        )

    def select_route(
        self,
        task_category: str,
        is_offline: bool = False,
        requires_vision: bool = False,
        allow_cloud: bool = True,
    ) -> ModelRoute:
        """Select optimal model provider and target based on task requirements."""
        # Offline or cloud disabled -> strictly local model
        if is_offline or not allow_cloud:
            return ModelRoute(
                provider="local",
                model_name=self.DEFAULT_MODELS["local"],
                task_category="offline",
                cost_tier="free",
                reasoning_depth="standard",
                rationale="Offline mode or cloud egress disabled; routed to local Gemma model.",
            )

        # Vision tasks -> Gemini
        if requires_vision or task_category == "vision":
            return ModelRoute(
                provider="gemini",
                model_name=self.DEFAULT_MODELS["gemini_vision"],
                task_category="vision",
                cost_tier="moderate",
                reasoning_depth="standard",
                rationale="Multimodal visual understanding requires Gemini vision model.",
            )

        # Complex reasoning & deep deliberation -> Token Harbor DeepSeek-R1
        if task_category in {"complex_reasoning", "serious_mode", "deliberation"}:
            return ModelRoute(
                provider="tokenharbor",
                model_name=self.DEFAULT_MODELS["tokenharbor_reasoning"],
                task_category="complex_reasoning",
                cost_tier="moderate",
                reasoning_depth="deep",
                rationale="Mission-critical reasoning routed to DeepSeek-R1 on Token Harbor.",
            )

        # Coding and technical implementation -> Groq Qwen Coder
        if task_category in {"coding", "software_engineering", "code_review"}:
            return ModelRoute(
                provider="groq",
                model_name=self.DEFAULT_MODELS["groq_coding"],
                task_category="coding",
                cost_tier="low",
                reasoning_depth="standard",
                rationale="Software engineering task routed to Qwen-2.5-Coder on Groq.",
            )

        # Default conversational / general knowledge -> Groq Qwen or Local
        return ModelRoute(
            provider="groq",
            model_name=self.DEFAULT_MODELS["groq_conversation"],
            task_category="conversation",
            cost_tier="free",
            reasoning_depth="standard",
            rationale="Standard conversational request routed to efficient Qwen model on Groq.",
        )
