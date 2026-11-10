import asyncio
import pytest
from sight_core.cognitive import (
    InputUnderstanding,
    IntentType,
    ContextManager,
    ReasoningEngine,
    PlanningEngine,
    Plan,
    PlanStep,
    StepStatus,
    DecisionEngine,
    RiskLevel,
    ResponseEngine,
    SeriousModeEngine,
    VerificationEngine,
    CognitiveOrchestrator,
)
from sight_core.routing import CloudProvider, ProviderPolicy


# =====================================================================
# 1. Input Understanding Tests
# =====================================================================

def test_intent_classification_conversation():
    nlu = InputUnderstanding()
    parsed = nlu.parse("What is the speed of light in vacuum?")
    assert parsed.intent == IntentType.CONVERSATION
    assert parsed.confidence >= 0.8
    assert not parsed.is_ambiguous


def test_intent_classification_tool_action():
    nlu = InputUnderstanding()
    parsed = nlu.parse("Create a file named notes.txt with meeting summary")
    assert parsed.intent == IntentType.TOOL_ACTION
    assert "notes.txt" in parsed.entities.get("files", [])
    assert parsed.entities.get("primary_file") == "notes.txt"


def test_intent_classification_multi_step_plan():
    nlu = InputUnderstanding()
    parsed = nlu.parse("Create a file named budget.txt and then open calculator")
    assert parsed.intent == IntentType.TASK_PLAN
    assert len(parsed.sub_instructions) == 2
    assert "budget.txt" in parsed.entities.get("files", [])
    assert parsed.entities.get("application") == "calculator"


def test_intent_classification_serious_mode():
    nlu = InputUnderstanding()
    parsed = nlu.parse("Serious mode: Should we migrate our primary database to PostgreSQL?")
    assert parsed.intent == IntentType.SERIOUS_MODE
    assert parsed.is_serious_mode_requested is True


def test_intent_classification_ambiguity_detection():
    nlu = InputUnderstanding()
    # Action without target file
    parsed = nlu.parse("Create a file")
    assert parsed.is_ambiguous is True
    assert "filename" in parsed.ambiguity_reason.lower()
    assert parsed.clarification_prompt is not None


# =====================================================================
# 2. Context Manager & Multi-Turn Retention Tests
# =====================================================================

def test_context_retention_and_anaphora_resolution():
    ctx = ContextManager()
    
    # Turn 1: User mentions a file
    ctx.add_turn("user", "Create a file named experiment.py", entities={"files": ["experiment.py"]})
    ctx.add_turn("assistant", "File experiment.py created.")

    assert ctx.active_entities.get("primary_file") == "experiment.py"

    # Turn 2: User refers to "that file"
    resolved = ctx.resolve_references("Now edit that file to add numpy")
    assert resolved.get("file_resolved") is True
    assert resolved.get("primary_file") == "experiment.py"


def test_context_task_tracking():
    ctx = ContextManager()
    task = ctx.track_task("task-100", "Generate quarterly report", total_steps=3)
    assert ctx.get_active_task() is not None
    assert ctx.get_active_task().status == "running"

    ctx.update_task("task-100", "completed", step_index=3)
    assert ctx.get_active_task() is None
    assert ctx.ongoing_tasks["task-100"].status == "completed"


# =====================================================================
# 3. Reasoning & Planning Engine Tests
# =====================================================================

def test_reasoning_task_decomposition():
    reasoner = ReasoningEngine()
    instructions = ["create a file named spec.md", "open notepad"]
    trace = reasoner.reason_about_task("Prepare specification document", sub_instructions=instructions)

    assert len(trace.sub_problems) == 2
    assert trace.sub_problems[0].id == "sub-1"
    assert trace.sub_problems[1].dependencies == ["sub-1"]
    assert trace.confidence >= 0.85


def test_planning_dependency_execution_order():
    reasoner = ReasoningEngine()
    planner = PlanningEngine()

    instructions = ["write data to log.txt", "open calculator"]
    trace = reasoner.reason_about_task("Log and calculate", sub_instructions=instructions)
    plan = planner.create_plan(trace, entities={"primary_file": "log.txt"})

    assert len(plan.steps) == 2
    ready = planner.get_ready_steps(plan)
    assert len(ready) == 1
    assert ready[0].id == "sub-1"

    # Mark step 1 complete -> step 2 becomes ready
    planner.mark_step(plan, "sub-1", StepStatus.COMPLETED, result={"status": "done"})
    ready_after = planner.get_ready_steps(plan)
    assert len(ready_after) == 1
    assert ready_after[0].id == "sub-2"


def test_dynamic_replanning_on_step_failure():
    planner = PlanningEngine()
    step1 = PlanStep(id="s1", description="fetch remote asset")
    step2 = PlanStep(id="s2", description="process asset", dependencies=["s1"])
    plan = Plan(goal="Process asset pipeline", steps=[step1, step2])

    planner.replan_on_failure(plan, "s1", "Network timeout occurred")
    assert plan.steps[0].status == StepStatus.FAILED
    assert plan.steps[1].status == StepStatus.CANCELLED
    assert "Dependent step 's1' failed" in plan.steps[1].result["reason"]


# =====================================================================
# 4. Decision Engine & Safety Permissions Tests
# =====================================================================

def test_permission_classification():
    decision = DecisionEngine()

    # Read-only
    p_read = decision.evaluate_permission("files.list")
    assert p_read.level == RiskLevel.READ_ONLY
    assert p_read.requires_human_approval is False

    # Reversible mutation
    p_rev = decision.evaluate_permission("files.create", {"name": "test.txt"})
    assert p_rev.level == RiskLevel.REVERSIBLE
    assert p_rev.requires_human_approval is True
    assert p_rev.reversible is True

    # Application launch
    p_app = decision.evaluate_permission("app.launch", {"application": "notepad"})
    assert p_app.level == RiskLevel.CONSEQUENTIAL
    assert p_app.requires_human_approval is True

    # Destructive
    p_dest = decision.evaluate_permission("history.clear")
    assert p_dest.level == RiskLevel.DESTRUCTIVE
    assert p_dest.requires_human_approval is True


def test_task_aware_model_routing():
    decision = DecisionEngine()

    # Offline -> Local
    r_offline = decision.select_route("conversation", is_offline=True)
    assert r_offline.provider == "local"
    assert "gemma" in r_offline.model_name

    # Complex reasoning -> Token Harbor DeepSeek-R1
    r_reason = decision.select_route("complex_reasoning")
    assert r_reason.provider == "tokenharbor"
    assert "deepseek-reasoner" in r_reason.model_name

    # Coding -> Groq Qwen Coder
    r_code = decision.select_route("coding")
    assert r_code.provider == "groq"
    assert "qwen" in r_code.model_name and "coder" in r_code.model_name

    # Vision -> Gemini
    r_vis = decision.select_route("vision")
    assert r_vis.provider == "gemini"


def test_tokenharbor_provider_contract(tmp_path):
    # Verify Token Harbor provider policy schema validation
    pol = ProviderPolicy(
        provider="tokenharbor",
        enabled=True,
        model="deepseek-reasoner",
        allow_remote_text=True,
        free_only=False,
        billing_enabled=True,
        daily_budget_usd=1.0,
        input_usd_per_million=0.5,
        output_usd_per_million=2.0,
    )
    assert pol.provider == "tokenharbor"
    assert pol.model == "deepseek-reasoner"


# =====================================================================
# 5. Serious Mode Multi-Model Deliberation Tests
# =====================================================================

@pytest.mark.anyio
async def test_serious_mode_deliberation_consensus():
    sm = SeriousModeEngine()
    result = await sm.deliberate("Should we implement automated rollback journals before file edits?")

    assert len(result.consultations) == 3
    assert result.deliberation_confidence >= 0.8
    assert "Serious Mode Deliberation Summary" in result.final_synthesis
    assert result.is_unanimous is True


@pytest.mark.anyio
async def test_serious_mode_contradiction_detection():
    sm = SeriousModeEngine()

    async def consult_a(task, p):
        from sight_core.cognitive.serious_mode import ModelConsultation
        return ModelConsultation(model_id="model-a", perspective=p, solution="This operation is feasible and safe.", reasoning_summary="", confidence=0.9)

    async def consult_b(task, p):
        from sight_core.cognitive.serious_mode import ModelConsultation
        return ModelConsultation(model_id="model-b", perspective=p, solution="This operation is impossible under current constraints.", reasoning_summary="", confidence=0.85)

    result = await sm.deliberate("Test conflict", custom_consultants=[consult_a, consult_b])
    assert len(result.detected_contradictions) >= 1
    assert result.is_unanimous is False
    assert "Divergent evaluation" in result.detected_contradictions[0].divergence_reason


# =====================================================================
# 6. Self-Correction & Outcome Verification Tests
# =====================================================================

def test_outcome_verification_truth_enforcement():
    verifier = VerificationEngine()

    # Honest failure detection
    v_fail = verifier.verify_tool_outcome("files.create", {"name": "test.txt"}, {"status": "unverified", "evidence": {"reason": "Hash mismatch"}})
    assert v_fail.is_verified is False
    assert v_fail.status == "unverified"
    assert "Hash mismatch" in v_fail.reason

    # Valid outcome
    v_pass = verifier.verify_tool_outcome(
        "files.create",
        {"name": "test.txt"},
        {"status": "done", "evidence": {"name": "test.txt", "sha256": "abc12345", "undo_id": "undo123"}},
    )
    assert v_pass.is_verified is True
    assert v_pass.status == "verified"


# =====================================================================
# 7. Cognitive Orchestrator End-to-End Tests
# =====================================================================

@pytest.mark.anyio
async def test_orchestrator_multi_step_proposal():
    orch = CognitiveOrchestrator()
    res = await orch.process_turn("Create a file named experiment.txt and then open notepad")

    assert res["status"] == "ok"
    assert res["intent"] == "task_plan"
    assert res["outcome"] == "pending_confirmation"
    assert "plan" in res
    assert len(res["plan"]["steps"]) == 2
    assert "I have formulated a 2-step plan" in res["say"]


@pytest.mark.anyio
async def test_orchestrator_ambiguity_clarification():
    orch = CognitiveOrchestrator()
    res = await orch.process_turn("Open the app")

    assert res["status"] == "ok"
    assert res["needs_clarification"] is True
    assert "Before I proceed, sir:" in res["say"]
