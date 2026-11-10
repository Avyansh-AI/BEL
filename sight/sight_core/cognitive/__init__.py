"""BEL Cognitive Architecture & Core Intelligence Package.

Provides natural language understanding, context management, multi-step reasoning,
action planning, task-aware model routing, Serious Mode multi-model consultation,
and outcome verification.
"""
from .understanding import InputUnderstanding, IntentType, ParsedInput
from .context import ContextManager, ConversationContext, TaskState
from .reasoning import ReasoningEngine, ReasoningTrace, SubProblem
from .planning import PlanningEngine, Plan, PlanStep, StepStatus
from .decision import DecisionEngine, RiskLevel, ActionPermission, ModelRoute
from .response import ResponseEngine
from .serious_mode import SeriousModeEngine, DeliberationResult
from .verification import VerificationEngine, VerificationResult
from .orchestrator import CognitiveOrchestrator

__all__ = [
    "InputUnderstanding",
    "IntentType",
    "ParsedInput",
    "ContextManager",
    "ConversationContext",
    "TaskState",
    "ReasoningEngine",
    "ReasoningTrace",
    "SubProblem",
    "PlanningEngine",
    "Plan",
    "PlanStep",
    "StepStatus",
    "DecisionEngine",
    "RiskLevel",
    "ActionPermission",
    "ModelRoute",
    "ResponseEngine",
    "SeriousModeEngine",
    "DeliberationResult",
    "VerificationEngine",
    "VerificationResult",
    "CognitiveOrchestrator",
]
