"""Types and Data Models for BEL Recursive Self-Improvement (RSI) Subsystem.

Defines schemas for capability gap detection (Scout), autonomous skill synthesis
(Forge Master), AST validation, self-healing diagnostics, and immutable versioning.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal
from pydantic import Field
from ..tools import StrictModel


class GapType(str, Enum):
    """Categorization of capability deficiencies detected by Scout."""
    MISSING_TOOL = "missing_tool"
    EXECUTION_FAILURE = "execution_failure"
    EFFICIENCY_BOTTLENECK = "efficiency_bottleneck"
    USER_REQUESTED_EXTENSION = "user_requested_extension"


class CapabilityGap(StrictModel):
    """Identified deficiency or extension opportunity discovered during cognition."""
    id: str
    user_request: str
    detected_intent: str
    gap_type: GapType
    missing_capability: str
    suggested_tool_name: str
    context: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class TestCase(StrictModel):
    """A declarative test specification verifying synthesized tool behavior."""
    __test__ = False  # Prevent pytest from attempting to collect as test suite
    name: str = Field(min_length=1, max_length=100)
    input_data: dict[str, Any] = Field(default_factory=dict)
    expected_output: Any = None
    expected_type: str | None = None


class CandidateSkill(StrictModel):
    """A synthesized, immutable executable skill candidate awaiting validation."""
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=5, max_length=500)
    code: str = Field(min_length=10, max_length=50000)
    test_cases: list[TestCase] = Field(min_length=1, max_length=20)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    version: int = Field(default=1, ge=1)
    created_at: float = Field(default_factory=time.time)
    project_id: str = Field(default="default", pattern=r"^[A-Za-z0-9_-]{1,80}$")
    permissions: list[str] = Field(default_factory=lambda: ["sandbox.execute"])


class TestExecutionResult(StrictModel):
    """Outcome of running validation test suite against a candidate in sandbox."""
    passed: bool
    total_cases: int
    passed_cases: int
    failed_cases: int
    case_details: list[dict[str, Any]] = Field(default_factory=list)
    execution_time_ms: float = 0.0
    error_message: str | None = None


class DiagnosticReport(StrictModel):
    """Detailed fault diagnosis derived from caught execution traceback."""
    error_type: str
    exception_message: str
    failing_file: str | None = None
    failing_line: int | None = None
    sanitized_traceback: str
    is_protected_core: bool = False
    diagnosis: str
    suggested_fix: str | None = None


class AutoHealResult(StrictModel):
    """Result of an autonomous self-healing attempt on failing components."""
    repair_id: str
    status: Literal["repaired", "rejected", "failed", "blocked_protected_file"]
    target_component: str
    original_digest: str | None = None
    patched_digest: str | None = None
    diff: str | None = None
    rollback_journal_id: str | None = None
    tests_passed: bool = False
    reason: str
