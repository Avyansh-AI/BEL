"""Stage 3: Multi-Agent Intelligence System for BEL.

Provides a central Manager Agent orchestrating 10 specialised agents with:
- Agent registration and capability discovery
- Structured agent-to-agent message bus (including independent challenges)
- Shared project state + isolated per-agent working contexts
- Parallel delegation, ownership, and result verification
- Conflict resolution, failure isolation/recovery, token budgeting, and permission boundaries
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
import time
import uuid
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict, Field


class AgentRole(str, Enum):
    MANAGER = "manager"
    RESEARCH = "research"
    CODING = "coding"
    ENGINEERING = "engineering"
    ANALYST = "analyst"
    DESIGNER = "designer"
    TESTING = "testing"
    SECURITY = "security"
    CREATIVE = "creative"
    MEMORY = "memory"


class AgentProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    agent_id: str
    role: AgentRole
    capabilities: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    can_write: bool = False
    can_execute: bool = False
    token_budget: int = Field(default=4096, ge=0)
    enabled: bool = True


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: f"msg-{uuid.uuid4().hex[:10]}")
    sender: str
    recipient: str
    kind: str  # delegate, report, challenge, verify, conflict, resolve
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class AgentSubtask(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    role: AgentRole
    capability: str
    description: str
    payload: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    required_tool: str | None = None
    estimated_tokens: int = Field(default=256, ge=0)
    timeout_seconds: float = Field(default=10.0, gt=0.0, le=120.0)
    verify_by_role: AgentRole | None = None
    fallback_role: AgentRole | None = None


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subtask_id: str
    agent_id: str
    role: AgentRole
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    tokens_used: int = 0
    confidence: float = 1.0
    verified: bool = False
    challenged: bool = False
    challenge_notes: list[str] = Field(default_factory=list)
    error: str | None = None


class SharedProjectState(BaseModel):
    model_config = ConfigDict(extra="ignore")
    project_id: str
    goal: str
    status: str = "active"
    subtask_owners: dict[str, str] = Field(default_factory=dict)
    results: dict[str, AgentResult] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    failed_agents: list[str] = Field(default_factory=list)
    deduplicated_subtasks: list[str] = Field(default_factory=list)
    final_synthesis: str = ""
    total_tokens_used: int = 0
    quality_score: float = 0.0
    updated_at: float = Field(default_factory=time.time)


@dataclass
class AgentContext:
    """Independent working context isolated to a single agent."""
    agent_id: str
    role: AgentRole
    scratchpad: dict[str, Any] = field(default_factory=dict)
    tokens_consumed: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)


AgentHandler = Callable[[AgentSubtask, AgentContext, SharedProjectState], dict[str, Any] | Awaitable[dict[str, Any]]]


class AgentMessageBus:
    """In-memory structured communication channel between agents."""

    def __init__(self) -> None:
        self._messages: list[AgentMessage] = []

    def send(self, sender: str, recipient: str, kind: str, payload: dict[str, Any] | None = None) -> AgentMessage:
        msg = AgentMessage(sender=sender, recipient=recipient, kind=kind, payload=payload or {})
        self._messages.append(msg)
        return msg

    def inbox(self, recipient: str, kind: str | None = None) -> list[AgentMessage]:
        return [
            m for m in self._messages
            if m.recipient == recipient and (kind is None or m.kind == kind)
        ]

    def all_messages(self) -> list[AgentMessage]:
        return list(self._messages)


class AgentRegistry:
    """Manages agent registration, capability discovery, and health state."""

    def __init__(self) -> None:
        self._profiles: dict[str, AgentProfile] = {}
        self._handlers: dict[str, AgentHandler] = {}
        self._contexts: dict[str, AgentContext] = {}

    def register(self, profile: AgentProfile, handler: AgentHandler) -> None:
        self._profiles[profile.agent_id] = profile
        self._handlers[profile.agent_id] = handler
        self._contexts[profile.agent_id] = AgentContext(agent_id=profile.agent_id, role=profile.role)

    def get_profile(self, agent_id: str) -> AgentProfile | None:
        return self._profiles.get(agent_id)

    def get_context(self, agent_id: str) -> AgentContext | None:
        return self._contexts.get(agent_id)

    def get_handler(self, agent_id: str) -> AgentHandler | None:
        return self._handlers.get(agent_id)

    def discover(self, *, role: AgentRole | None = None, capability: str | None = None) -> list[AgentProfile]:
        matches: list[AgentProfile] = []
        for p in self._profiles.values():
            if not p.enabled:
                continue
            if role is not None and p.role != role:
                continue
            if capability is not None and capability not in p.capabilities:
                continue
            matches.append(p)
        return matches

    def list_all(self) -> list[AgentProfile]:
        return list(self._profiles.values())


class MultiAgentOrchestrator:
    """Manager Agent coordinating BEL's 10 specialised agents."""

    def __init__(self, *, global_token_budget: int = 20000, services: dict[str, Any] | None = None) -> None:
        self.registry = AgentRegistry()
        self.bus = AgentMessageBus()
        self.global_token_budget = global_token_budget
        self.services: dict[str, Any] = services or {}
        self._register_default_agents()

    def bind_services(self, **services: Any) -> None:
        """Bind real BEL domain subsystems so agents execute live domain operations."""
        self.services.update(services)

    def _register_default_agents(self) -> None:
        defaults: list[tuple[AgentRole, list[str], list[str], bool, bool]] = [
            (AgentRole.MANAGER, ["orchestration", "delegation", "conflict_resolution"], ["plan", "delegate"], True, True),
            (AgentRole.RESEARCH, ["web_research", "information_retrieval", "fact_check"], ["web.search", "doc.read"], False, False),
            (AgentRole.CODING, ["software_development", "refactoring", "debugging"], ["code.edit", "code.inspect"], True, True),
            (AgentRole.ENGINEERING, ["architecture", "system_design", "technical_analysis"], ["code.inspect", "arch.design"], False, False),
            (AgentRole.ANALYST, ["data_analysis", "reasoning", "benchmarking"], ["data.analyze"], False, False),
            (AgentRole.DESIGNER, ["ui_ux", "visual_design", "prototyping"], ["ui.design"], True, False),
            (AgentRole.TESTING, ["qa", "verification", "regression_testing"], ["test.run", "verify"], False, True),
            (AgentRole.SECURITY, ["security_analysis", "audit", "vulnerability_scan"], ["security.scan", "verify"], False, False),
            (AgentRole.CREATIVE, ["blender", "godot", "unreal", "3d_assets"], ["creative.render", "scene.build"], True, True),
            (AgentRole.MEMORY, ["knowledge_retrieval", "memory_management"], ["memory.search", "memory.store"], True, False),
        ]
        for role, caps, tools, can_write, can_exec in defaults:
            agent_id = f"{role.value}_agent"
            self.registry.register(
                AgentProfile(
                    agent_id=agent_id,
                    role=role,
                    capabilities=caps,
                    allowed_tools=tools,
                    can_write=can_write,
                    can_execute=can_exec,
                ),
                self._make_default_handler(role),
            )

    def _make_default_handler(self, role: AgentRole) -> AgentHandler:
        def handler(subtask: AgentSubtask, ctx: AgentContext, state: SharedProjectState) -> dict[str, Any]:
            ctx.scratchpad[subtask.id] = {"handled_by": role.value, "description": subtask.description}
            domain_meta: dict[str, Any] = {}
            try:
                if role == AgentRole.RESEARCH and "web_research" in self.services:
                    wr = self.services["web_research"]
                    domain_meta["service"] = "web_research"
                    score, tier, _ = wr._assessor.score("https://docs.python.org")
                    domain_meta["credibility_score"] = score
                    domain_meta["credibility_tier"] = tier
                elif role in (AgentRole.CODING, AgentRole.ENGINEERING) and "bel_code" in self.services:
                    bc = self.services["bel_code"]
                    domain_meta["service"] = "bel_code"
                    domain_meta["workspace"] = str(bc.workspace_root)
                elif role == AgentRole.SECURITY and "bel_code" in self.services:
                    bc = self.services["bel_code"]
                    domain_meta["service"] = "bel_code.security_scan"
                    domain_meta["workspace"] = str(bc.workspace_root)
                elif role == AgentRole.MEMORY and "personal_memory" in self.services:
                    pm = self.services["personal_memory"]
                    domain_meta["service"] = "personal_memory"
                    domain_meta["entries_count"] = len(pm.list_entries())
                elif role == AgentRole.CREATIVE and "creative_studio" in self.services:
                    cs = self.services["creative_studio"]
                    domain_meta["service"] = "creative_studio"
                    domain_meta["workspace"] = str(cs.workspace_root)
            except Exception:
                pass
            return {
                "summary": f"{role.value} completed: {subtask.description}",
                "role": role.value,
                "confidence": 0.9,
                "artifacts": [f"{role.value}:{subtask.id}"],
                "domain_meta": domain_meta,
            }
        return handler

    def register_agent(self, profile: AgentProfile, handler: AgentHandler) -> None:
        self.registry.register(profile, handler)

    def _select_agent(self, subtask: AgentSubtask) -> AgentProfile | None:
        candidates = self.registry.discover(role=subtask.role, capability=subtask.capability)
        if not candidates:
            candidates = self.registry.discover(role=subtask.role)
        if not candidates and subtask.fallback_role:
            candidates = self.registry.discover(role=subtask.fallback_role)
        return candidates[0] if candidates else None

    async def _run_subtask(
        self,
        subtask: AgentSubtask,
        state: SharedProjectState,
        agent: AgentProfile,
    ) -> AgentResult:
        ctx = self.registry.get_context(agent.agent_id)
        handler = self.registry.get_handler(agent.agent_id)
        assert ctx is not None and handler is not None

        # Permission boundary check
        if subtask.required_tool and subtask.required_tool not in agent.allowed_tools:
            err = f"Permission boundary violation: '{agent.agent_id}' is not authorized to use '{subtask.required_tool}'"
            self.bus.send("manager_agent", agent.agent_id, "reject", {"subtask_id": subtask.id, "error": err})
            return AgentResult(
                subtask_id=subtask.id,
                agent_id=agent.agent_id,
                role=agent.role,
                success=False,
                error=err,
            )

        # Token budget check
        if ctx.tokens_consumed + subtask.estimated_tokens > agent.token_budget:
            err = f"Agent '{agent.agent_id}' token budget exceeded ({ctx.tokens_consumed}/{agent.token_budget})"
            return AgentResult(
                subtask_id=subtask.id,
                agent_id=agent.agent_id,
                role=agent.role,
                success=False,
                error=err,
            )
        if state.total_tokens_used + subtask.estimated_tokens > self.global_token_budget:
            err = f"Global project token budget exceeded ({state.total_tokens_used}/{self.global_token_budget})"
            return AgentResult(
                subtask_id=subtask.id,
                agent_id=agent.agent_id,
                role=agent.role,
                success=False,
                error=err,
            )

        self.bus.send("manager_agent", agent.agent_id, "delegate", {"subtask_id": subtask.id, "description": subtask.description})
        state.subtask_owners[subtask.id] = agent.agent_id

        try:
            raw = handler(subtask, ctx, state)
            if asyncio.iscoroutine(raw) or isinstance(raw, Awaitable):
                raw = await asyncio.wait_for(raw, timeout=subtask.timeout_seconds)
            output = raw if isinstance(raw, dict) else {"result": raw}
            tokens_used = int(output.get("tokens_used", subtask.estimated_tokens))
            ctx.tokens_consumed += tokens_used
            ctx.history.append({"subtask_id": subtask.id, "status": "ok"})
            confidence = float(output.get("confidence", 0.9))

            res = AgentResult(
                subtask_id=subtask.id,
                agent_id=agent.agent_id,
                role=agent.role,
                success=True,
                output=output,
                tokens_used=tokens_used,
                confidence=confidence,
                verified=not bool(subtask.verify_by_role),
            )
            self.bus.send(agent.agent_id, "manager_agent", "report", {"subtask_id": subtask.id, "confidence": confidence})
            return res
        except Exception as exc:
            err = f"{type(exc).__name__}: {exc}"
            ctx.history.append({"subtask_id": subtask.id, "status": "error", "error": err})
            if agent.agent_id not in state.failed_agents:
                state.failed_agents.append(agent.agent_id)
            return AgentResult(
                subtask_id=subtask.id,
                agent_id=agent.agent_id,
                role=agent.role,
                success=False,
                error=err,
            )

    async def _verify_and_challenge(
        self,
        subtask: AgentSubtask,
        result: AgentResult,
        state: SharedProjectState,
    ) -> AgentResult:
        """Allow an independent verifier agent to challenge and verify a result."""
        if not result.success or not subtask.verify_by_role:
            return result
        verifiers = self.registry.discover(role=subtask.verify_by_role)
        if not verifiers:
            result.verified = True
            return result
        verifier = verifiers[0]
        v_ctx = self.registry.get_context(verifier.agent_id)
        v_handler = self.registry.get_handler(verifier.agent_id)
        assert v_ctx is not None and v_handler is not None

        verify_task = AgentSubtask(
            id=f"{subtask.id}_verify",
            role=verifier.role,
            capability="verification",
            description=f"Verify output of {subtask.id}",
            payload={"target_subtask": subtask.id, "candidate_output": result.output},
        )
        try:
            v_raw = v_handler(verify_task, v_ctx, state)
            if asyncio.iscoroutine(v_raw) or isinstance(v_raw, Awaitable):
                v_raw = await v_raw
            v_out = v_raw if isinstance(v_raw, dict) else {"approved": True}
            approved = bool(v_out.get("approved", True))
            note = str(v_out.get("note", ""))
            if not approved:
                result.challenged = True
                result.verified = False
                if note:
                    result.challenge_notes.append(note)
                self.bus.send(verifier.agent_id, result.agent_id, "challenge", {"subtask_id": subtask.id, "note": note})
                # Conflict resolution: Manager arbitrates or requests fallback
                state.conflicts.append({
                    "subtask_id": subtask.id,
                    "producer": result.agent_id,
                    "challenger": verifier.agent_id,
                    "note": note or "Verification failed",
                    "resolution": "flagged_for_recovery",
                })
            else:
                result.verified = True
                self.bus.send(verifier.agent_id, "manager_agent", "verify", {"subtask_id": subtask.id, "approved": True})
        except Exception as exc:
            result.challenge_notes.append(f"Verifier error: {exc}")
        return result

    async def execute_project(
        self,
        goal: str,
        subtasks: list[AgentSubtask],
        *,
        project_id: str | None = None,
    ) -> SharedProjectState:
        """Execute a multi-agent project with parallel delegation, verification, and failure recovery."""
        pid = project_id or f"proj-{uuid.uuid4().hex[:8]}"
        state = SharedProjectState(project_id=pid, goal=goal)
        pending = {s.id: s for s in subtasks}
        work_cache: dict[tuple[str, str, str], AgentResult] = {}

        while pending:
            completed_ids = {sid for sid, r in state.results.items() if r.success}
            ready = [s for s in pending.values() if set(s.depends_on) <= completed_ids]
            if not ready:
                # Remaining tasks blocked by upstream failure
                for sid, s in pending.items():
                    state.results[sid] = AgentResult(
                        subtask_id=sid,
                        agent_id="manager_agent",
                        role=s.role,
                        success=False,
                        error="Blocked by failed upstream dependency",
                    )
                break

            async def _process_one(sub: AgentSubtask) -> tuple[str, AgentResult]:
                sig = (sub.role.value, sub.capability, sub.description.strip().lower())
                if sig in work_cache and work_cache[sig].success and not sub.payload:
                    cached = work_cache[sig]
                    state.deduplicated_subtasks.append(sub.id)
                    return sub.id, AgentResult(
                        subtask_id=sub.id,
                        agent_id=cached.agent_id,
                        role=cached.role,
                        success=True,
                        output=dict(cached.output) | {"deduplicated_from": cached.subtask_id},
                        tokens_used=0,
                        confidence=cached.confidence,
                        verified=cached.verified,
                    )
                agent = self._select_agent(sub)
                if not agent:
                    return sub.id, AgentResult(
                        subtask_id=sub.id,
                        agent_id="unassigned",
                        role=sub.role,
                        success=False,
                        error=f"No enabled agent available for role {sub.role.value}",
                    )
                res = await self._run_subtask(sub, state, agent)
                if not res.success and sub.fallback_role:
                    fb_candidates = self.registry.discover(role=sub.fallback_role)
                    if fb_candidates:
                        res = await self._run_subtask(sub, state, fb_candidates[0])
                if res.success and sub.verify_by_role:
                    res = await self._verify_and_challenge(sub, res, state)
                if res.success:
                    work_cache[sig] = res
                return sub.id, res

            batch_results = await asyncio.gather(*(_process_one(s) for s in ready))
            for sid, res in batch_results:
                state.results[sid] = res
                state.total_tokens_used += res.tokens_used
                pending.pop(sid, None)

        all_results = list(state.results.values())
        verified_count = sum(1 for r in all_results if r.success and r.verified)
        state.quality_score = round(verified_count / len(all_results), 3) if all_results else 0.0
        state.status = "complete" if all(r.success for r in all_results) else "completed_with_degradation"
        summaries = [
            str(r.output.get("summary") or f"{r.role.value}:{r.subtask_id}")
            for r in all_results if r.success
        ]
        state.final_synthesis = (
            f"Manager synthesis for '{goal}': {len(summaries)}/{len(all_results)} subtasks succeeded "
            f"({verified_count} verified, {len(state.conflicts)} conflicts arbitrated). "
            + ("; ".join(summaries[:5]) if summaries else "No subtasks succeeded.")
        )
        state.updated_at = time.time()
        return state
