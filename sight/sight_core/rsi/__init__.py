"""BEL Recursive Self-Improvement (RSI) Package.

Delivers:
- Scout: Capability gap and bottleneck detection.
- Forge Master: Autonomous tool and skill synthesis with AST safety audits.
- Sandbox Testing: Isolated subprocess test execution and verification.
- Auto-Heal: Fault diagnosis, surgical patching, and atomic rollback journals.
- Immutable Governance: Protected core invariants, versioning, and cryptographic digests.
"""
from __future__ import annotations

from .auto_heal import AutoHealEngine
from .boundaries import (
    ALLOWED_SKILL_IMPORTS,
    PROTECTED_CORE_FILES,
    assert_safe_modification,
    audit_code_safety,
    is_protected_file,
)
from .engine import RecursiveSelfImprovementEngine
from .scout import CapabilityScout
from .synthesizer import ToolSynthesizer
from .types import (
    AutoHealResult,
    CandidateSkill,
    CapabilityGap,
    DiagnosticReport,
    GapType,
    SkillQualityReport,
    TestCase,
    TestExecutionResult,
)

__all__ = [
    "ALLOWED_SKILL_IMPORTS",
    "AutoHealEngine",
    "AutoHealResult",
    "CandidateSkill",
    "CapabilityGap",
    "CapabilityScout",
    "DiagnosticReport",
    "GapType",
    "PROTECTED_CORE_FILES",
    "RecursiveSelfImprovementEngine",
    "SkillQualityReport",
    "TestCase",
    "TestExecutionResult",
    "ToolSynthesizer",
    "assert_safe_modification",
    "audit_code_safety",
    "is_protected_file",
]
