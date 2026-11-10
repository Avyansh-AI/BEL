"""Comprehensive Test Suite for BEL Stage 4: Recursive Self-Improvement (RSI).

Covers:
1. Protected core security boundary invariants and AST code auditing.
2. Scout capability gap detection from conversational input and execution failures.
3. Forge Master autonomous tool synthesis, test generation, and SHA-256 digest.
4. Isolated sandbox test execution and timeout enforcement.
5. Auto-Heal traceback diagnosis, fault classification, surgical hotfix, and rollback.
6. Master RSI engine lifecycle: Gap -> Synthesize -> Test -> Promote -> Rollback.
7. Cognitive orchestrator integration with synthesized tool proposal.
8. Learning API REST endpoints for RSI actions and status.
"""
from __future__ import annotations

import tempfile
import pytest

from sight_core.brain_store import BrainStore
from sight_core.rsi import (
    AutoHealEngine,
    CandidateSkill,
    CapabilityGap,
    CapabilityScout,
    GapType,
    PROTECTED_CORE_FILES,
    RecursiveSelfImprovementEngine,
    TestCase,
    ToolSynthesizer,
    assert_safe_modification,
    audit_code_safety,
    is_protected_file,
)
from sight_core.cognitive.orchestrator import CognitiveOrchestrator


@pytest.fixture
def temp_brain():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = BrainStore(tmp_dir)
        yield store


# =====================================================================
# 1. Protected Boundary & AST Safety Tests
# =====================================================================

def test_protected_core_boundary_invariants():
    # Verify core files list
    assert "security.py" in PROTECTED_CORE_FILES
    assert "brain_store.py" in PROTECTED_CORE_FILES
    assert "decision.py" in PROTECTED_CORE_FILES
    assert "verification.py" in PROTECTED_CORE_FILES
    assert "system_monitor.py" in PROTECTED_CORE_FILES
    assert "boundaries.py" in PROTECTED_CORE_FILES

    # Path checking
    assert is_protected_file("security.py") is True
    assert is_protected_file("sight_core/brain_store.py") is True
    assert is_protected_file("C:\\Path\\To\\decision.py") is True
    assert is_protected_file("my_tool.py") is False

    # PermissionError enforcement
    with pytest.raises(PermissionError, match="protected core safety kernel"):
        assert_safe_modification("security.py")

    # Safe file does not raise
    assert_safe_modification("custom_converter.py")


def test_ast_security_auditor():
    # Safe code
    safe_code = """
def add_numbers(a: int, b: int) -> int:
    return a + b
"""
    is_safe, error = audit_code_safety(safe_code)
    assert is_safe is True
    assert error is None

    # Dangerous code: eval
    eval_code = "def dangerous(x): return eval(x)"
    is_safe_eval, err_eval = audit_code_safety(eval_code)
    assert is_safe_eval is False
    assert "eval" in err_eval

    # Dangerous code: os.system
    os_code = "import os\ndef pwn(): os.system('calc')"
    is_safe_os, err_os = audit_code_safety(os_code)
    assert is_safe_os is False
    assert "os.system" in err_os

    # Syntax error handling
    syntax_err_code = "def bad_syntax(: return"
    is_safe_syn, err_syn = audit_code_safety(syntax_err_code)
    assert is_safe_syn is False
    assert "Syntax Error" in err_syn


# =====================================================================
# 2. Scout Capability Gap Detection Tests
# =====================================================================

def test_scout_capability_gap_detection():
    scout = CapabilityScout()

    # 1. Explicit request to build a tool
    gap1 = scout.inspect_request(
        "Please create a new tool called base64_encoder",
        detected_intent="tool_action",
    )
    assert gap1 is not None
    assert gap1.gap_type == GapType.USER_REQUESTED_EXTENSION
    assert gap1.suggested_tool_name == "base64_encoder"

    # 2. Implicit common utility gap: temperature conversion
    gap2 = scout.inspect_request(
        "Convert 100 Celsius to Fahrenheit",
        detected_intent="conversation",
    )
    assert gap2 is not None
    assert gap2.gap_type == GapType.MISSING_TOOL
    assert gap2.suggested_tool_name == "temperature_converter"

    # 3. Execution failure gap detection
    gap3 = scout.inspect_failure(
        tool_name="git.sync",
        error_message="Connection reset by peer: SSH timeout",
    )
    assert gap3 is not None
    assert gap3.gap_type == GapType.EXECUTION_FAILURE
    assert gap3.suggested_tool_name == "git.sync"

    # 4. Standard conversational query without tool gap
    gap_none = scout.inspect_request("Hello BEL, how are you today?", "conversation")
    assert gap_none is None


# =====================================================================
# 3. Forge Master Tool Synthesis & Sandbox Testing Tests
# =====================================================================

def test_forge_master_tool_synthesis_and_sandbox_execution():
    synth = ToolSynthesizer()
    gap = CapabilityGap(
        id="gap-test-1",
        user_request="Convert 100 Celsius to Fahrenheit",
        detected_intent="conversation",
        gap_type=GapType.MISSING_TOOL,
        missing_capability="Temperature conversion between C, F, K.",
        suggested_tool_name="temperature_converter",
    )

    candidate = synth.synthesize_tool_template(gap)
    assert candidate.id.startswith("skill_")
    assert len(candidate.digest) == 64
    assert len(candidate.test_cases) >= 2

    # Execute sandbox tests
    test_result = synth.run_tests(candidate)
    assert test_result.passed is True
    assert test_result.passed_cases == test_result.total_cases
    assert test_result.failed_cases == 0
    assert test_result.execution_time_ms >= 0.0


def test_sandbox_test_runner_catches_failures_and_timeouts():
    synth = ToolSynthesizer()

    # Intentionally failing test case
    failing_code = """
def execute_tool(value: int) -> int:
    return value + 1
"""
    failing_tests = [
        TestCase(name="Expected 100", input_data={"value": 10}, expected_output=100)
    ]
    candidate = synth.synthesize_tool_template(
        CapabilityGap(
            id="gap-fail",
            user_request="test request",
            detected_intent="test",
            gap_type=GapType.MISSING_TOOL,
            missing_capability="Failing math capability",
            suggested_tool_name="failing_math",
        ),
        custom_code=failing_code,
        custom_tests=failing_tests,
    )

    res = synth.run_tests(candidate)
    assert res.passed is False
    assert res.failed_cases == 1

    # Timeout test case
    timeout_code = """
def execute_tool() -> int:
    import time
    time.sleep(5)
    return 42
"""
    timeout_tests = [TestCase(name="Sleep Timeout", input_data={}, expected_output=42)]
    timeout_cand = synth.synthesize_tool_template(
        CapabilityGap(
            id="gap-timeout",
            user_request="timeout request",
            detected_intent="test",
            gap_type=GapType.MISSING_TOOL,
            missing_capability="Timeout execution capability",
            suggested_tool_name="timeout_tool",
        ),
        custom_code=timeout_code,
        custom_tests=timeout_tests,
    )

    t_res = synth.run_tests(timeout_cand, timeout_seconds=0.5)
    assert t_res.passed is False
    assert "timed out" in t_res.error_message


# =====================================================================
# 4. Auto-Heal Diagnostics & Surgical Patching Tests
# =====================================================================

def test_auto_heal_diagnostics_and_surgical_patch(temp_brain):
    auto_heal = AutoHealEngine(store=temp_brain)

    # 1. Diagnose ZeroDivisionError
    try:
        1 / 0
    except ZeroDivisionError as exc:
        report = auto_heal.diagnose(exc)
        assert report.error_type == "ZeroDivisionError"
        assert "Division by zero" in report.diagnosis
        assert report.is_protected_core is False

    # 2. Attempt surgical heal on failing skill
    failing_tool = """def execute_tool(a: float, b: float) -> float:
    return a / b
"""
    res = auto_heal.attempt_skill_heal(
        skill_id="div_tool",
        failing_code=failing_tool,
        error_report=report,
    )
    assert res.status == "repaired"
    assert res.tests_passed is True
    assert res.diff is not None
    assert res.rollback_journal_id in auto_heal.rollback_journals

    # 3. Rollback
    rollback_res = auto_heal.rollback(res.rollback_journal_id)
    assert rollback_res["status"] == "rolled_back"
    assert rollback_res["restored_code"] == failing_tool


def test_auto_heal_refuses_protected_core_files(temp_brain):
    auto_heal = AutoHealEngine(store=temp_brain)
    from sight_core.rsi.types import DiagnosticReport

    # Construct report pointing to security.py
    report = DiagnosticReport(
        error_type="ValueError",
        exception_message="Invalid token",
        failing_file="c:/sight/sight_core/security.py",
        failing_line=42,
        sanitized_traceback="",
        is_protected_core=True,
        diagnosis="Error in security.py",
    )

    res = auto_heal.attempt_skill_heal("security_patch", "code", report)
    assert res.status == "blocked_protected_file"
    assert "protected security kernel" in res.reason


# =====================================================================
# 5. Master RSI Engine Lifecycle Tests
# =====================================================================

def test_master_rsi_engine_extension_lifecycle(temp_brain):
    engine = RecursiveSelfImprovementEngine(store=temp_brain)

    # 1. Scout & Synthesize
    gap, candidate, test_res = engine.process_request_for_extensions(
        user_request="Can you calculate sha256 checksum for text?",
        detected_intent="conversation",
    )
    assert gap is not None
    assert candidate is not None
    assert test_res.passed is True

    # 2. Verify stored in candidates table
    with temp_brain.connect() as db:
        c_row = db.execute("SELECT * FROM candidates WHERE digest = ?", (candidate.digest,)).fetchone()
        assert c_row is not None
        assert c_row["state"] == "tested"
        candidate_id = c_row["id"]

    # 3. Promote Candidate to Procedures
    promote_res = engine.promote_candidate(candidate_id, candidate.digest)
    assert promote_res["status"] == "active"
    assert promote_res["version"] == 1

    # 4. Promote new version
    # Synthesize v2 with additional test
    candidate_v2 = CandidateSkill(
        id=candidate.id,
        name=candidate.name,
        description=candidate.description,
        code=candidate.code + "\n# Enhanced version 2",
        test_cases=candidate.test_cases,
        digest="a" * 64,
        version=2,
    )
    cid_v2 = engine._save_candidate(candidate_v2, test_res)
    promote_v2 = engine.promote_candidate(cid_v2, candidate_v2.digest)
    assert promote_v2["version"] == 2
    assert promote_v2["rollback_target"] == 1

    # 5. Rollback to Version 1
    rb_res = engine.rollback_skill(candidate.id, target_version=1)
    assert rb_res["active_version"] == 1
    assert rb_res["status"] == "rolled_back"


# =====================================================================
# 6. Cognitive Orchestrator Integration Tests
# =====================================================================

@pytest.mark.anyio
async def test_cognitive_orchestrator_rsi_synthesis_turn(temp_brain):
    engine = RecursiveSelfImprovementEngine(store=temp_brain)
    orch = CognitiveOrchestrator(rsi=engine)

    turn_res = await orch.process_turn("Create a new tool to convert temperature from Celsius to Fahrenheit")
    assert turn_res["status"] == "ok"
    assert turn_res["intent"] == "rsi_synthesis"
    assert turn_res["outcome"] == "ready_for_promotion"
    assert "candidate" in turn_res
    assert "All" in turn_res["say"] and "validation tests passed cleanly" in turn_res["say"]


# =====================================================================
# 7. Learning API RSI REST Endpoints Tests
# =====================================================================

def test_learning_api_rsi_endpoints(client):
    def invoke(operation, args):
        path = "/api/learning/" + operation
        prepared = client.post("/api/actions/prepare", json={"path": path, "args": args})
        assert prepared.status_code == 200, prepared.text
        grant = prepared.json()
        return client.post(path, json=grant["args"] | {"actionApproval": grant["approvalId"]})

    # 1. RSI Status
    status_res = client.get("/api/learning/rsi/status")
    assert status_res.status_code == 200
    st = status_res.json()
    assert st["enabled"] is True
    assert "security.py" in st["protected_core_files"]

    # 2. RSI Synthesize
    synth_res = invoke("rsi/synthesize", {
        "user_request": "Convert celsius to fahrenheit",
        "suggested_tool_name": "temp_conv",
        "missing_capability": "Temperature conversion utility",
    })
    assert synth_res.status_code == 200, synth_res.text
    cand_data = synth_res.json()
    assert cand_data["ready_for_promotion"] is True
    cid = cand_data["candidate_id"]
    digest = cand_data["candidate"]["digest"]

    # 3. RSI Promote
    promote_res = invoke("rsi/promote", {
        "candidate_id": cid,
        "expected_digest": digest,
    })
    assert promote_res.status_code == 200, promote_res.text
    assert promote_res.json()["status"] == "active"
    assert promote_res.json()["version"] == 1

    # 4. RSI Auto-Heal
    heal_res = invoke("rsi/auto_heal", {
        "skill_id": "div_tool",
        "error_type": "ZeroDivisionError",
        "error_message": "division by zero",
        "failing_code": "def execute_tool(a, b): return a / b",
    })
    assert heal_res.status_code == 200, heal_res.text
    assert heal_res.json()["status"] == "repaired"
