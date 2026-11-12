"""Stage 3 Verification Tests: Multi-Agent Intelligence."""
import asyncio
import time

from sight_core.multi_agent import (
    AgentContext,
    AgentProfile,
    AgentRole,
    AgentSubtask,
    MultiAgentOrchestrator,
    SharedProjectState,
)


def test_stage3_all_ten_agents_registered_and_discoverable():
    orch = MultiAgentOrchestrator()
    profiles = orch.registry.list_all()
    roles = {p.role for p in profiles}
    assert roles == set(AgentRole)
    assert len(orch.registry.discover(capability="blender")) == 1
    assert len(orch.registry.discover(role=AgentRole.SECURITY)) == 1


def test_stage3_parallel_collaboration_and_independent_contexts():
    orch = MultiAgentOrchestrator()
    started = {}

    async def slow_research(sub: AgentSubtask, ctx: AgentContext, state: SharedProjectState):
        started["research"] = time.monotonic()
        ctx.scratchpad["private_key"] = "research_only"
        await asyncio.sleep(0.1)
        return {"findings": ["fact_a"], "tokens_used": 100}

    async def slow_design(sub: AgentSubtask, ctx: AgentContext, state: SharedProjectState):
        started["designer"] = time.monotonic()
        ctx.scratchpad["private_key"] = "designer_only"
        await asyncio.sleep(0.1)
        return {"layout": "orb_v2", "tokens_used": 120}

    orch.register_agent(
        AgentProfile(agent_id="research_agent", role=AgentRole.RESEARCH, capabilities=["web_research"]),
        slow_research,
    )
    orch.register_agent(
        AgentProfile(agent_id="designer_agent", role=AgentRole.DESIGNER, capabilities=["ui_ux"]),
        slow_design,
    )

    subtasks = [
        AgentSubtask(id="t1", role=AgentRole.RESEARCH, capability="web_research", description="Research APIs"),
        AgentSubtask(id="t2", role=AgentRole.DESIGNER, capability="ui_ux", description="Design UI"),
        AgentSubtask(
            id="t3",
            role=AgentRole.CODING,
            capability="software_development",
            description="Implement UI",
            depends_on=["t1", "t2"],
        ),
    ]
    state = asyncio.run(orch.execute_project("Build feature", subtasks))
    assert state.status == "complete"
    assert abs(started["research"] - started["designer"]) < 0.08
    assert orch.registry.get_context("research_agent").scratchpad["private_key"] == "research_only"
    assert orch.registry.get_context("designer_agent").scratchpad["private_key"] == "designer_only"
    assert state.total_tokens_used > 0


def test_stage3_independent_challenge_and_conflict_resolution():
    orch = MultiAgentOrchestrator()

    def coding_handler(sub: AgentSubtask, ctx: AgentContext, state: SharedProjectState):
        return {"code": "eval(user_input)", "tokens_used": 80}

    def security_verifier(sub: AgentSubtask, ctx: AgentContext, state: SharedProjectState):
        code = sub.payload["candidate_output"].get("code", "")
        if "eval(" in code:
            return {"approved": False, "note": "Unsafe eval() detected"}
        return {"approved": True}

    orch.register_agent(
        AgentProfile(agent_id="coding_agent", role=AgentRole.CODING, capabilities=["software_development"], can_write=True),
        coding_handler,
    )
    orch.register_agent(
        AgentProfile(agent_id="security_agent", role=AgentRole.SECURITY, capabilities=["security_analysis", "verification"]),
        security_verifier,
    )

    subtasks = [
        AgentSubtask(
            id="impl",
            role=AgentRole.CODING,
            capability="software_development",
            description="Write parser",
            verify_by_role=AgentRole.SECURITY,
        )
    ]
    state = asyncio.run(orch.execute_project("Secure parser", subtasks))
    res = state.results["impl"]
    assert res.challenged is True
    assert res.verified is False
    assert "Unsafe eval() detected" in res.challenge_notes
    assert len(state.conflicts) == 1
    assert any(m.kind == "challenge" for m in orch.bus.all_messages())


def test_stage3_failure_isolation_and_fallback_recovery():
    orch = MultiAgentOrchestrator()

    def broken_creative(sub: AgentSubtask, ctx: AgentContext, state: SharedProjectState):
        raise RuntimeError("Blender crashed")

    orch.register_agent(
        AgentProfile(agent_id="creative_agent", role=AgentRole.CREATIVE, capabilities=["blender"]),
        broken_creative,
    )

    subtasks = [
        AgentSubtask(
            id="asset",
            role=AgentRole.CREATIVE,
            capability="blender",
            description="Generate 3D asset",
            fallback_role=AgentRole.ENGINEERING,
        ),
        AgentSubtask(
            id="analyze",
            role=AgentRole.ANALYST,
            capability="data_analysis",
            description="Independent analysis",
        ),
    ]
    state = asyncio.run(orch.execute_project("Resilient project", subtasks))
    assert state.status == "complete"
    assert "creative_agent" in state.failed_agents
    assert state.results["asset"].success is True
    assert state.results["asset"].role == AgentRole.ENGINEERING
    assert state.results["analyze"].success is True


def test_stage3_permission_boundary_and_token_budget():
    orch = MultiAgentOrchestrator(global_token_budget=500)
    subtasks = [
        AgentSubtask(
            id="unauthorized",
            role=AgentRole.RESEARCH,
            capability="web_research",
            description="Try forbidden tool",
            required_tool="code.edit",
        ),
        AgentSubtask(
            id="over_budget",
            role=AgentRole.ANALYST,
            capability="data_analysis",
            description="Huge analysis",
            estimated_tokens=600,
        ),
    ]
    state = asyncio.run(orch.execute_project("Boundary checks", subtasks))
    assert not state.results["unauthorized"].success
    assert "Permission boundary violation" in state.results["unauthorized"].error
    assert not state.results["over_budget"].success
    assert "budget exceeded" in state.results["over_budget"].error
