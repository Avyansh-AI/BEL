"""BEL Cognitive Orchestrator.

Unifies input understanding, conversational context tracking, multi-step
reasoning, plan generation, permission-aware decision making, Serious Mode
deliberation, outcome verification, and persona-aligned response generation.
"""
from __future__ import annotations

import time
import uuid
from typing import Any
from .understanding import InputUnderstanding, IntentType, ParsedInput
from .context import ContextManager, TaskState
from .reasoning import ReasoningEngine, ReasoningTrace
from .planning import PlanningEngine, Plan, PlanStep, StepStatus
from .decision import DecisionEngine, RiskLevel, ActionPermission, ModelRoute
from .response import ResponseEngine
from .serious_mode import SeriousModeEngine, DeliberationResult
from .verification import VerificationEngine, VerificationResult


class CognitiveOrchestrator:
    """Master cognitive orchestration engine for BEL."""

    def __init__(self, router=None, bel=None, memory=None) -> None:
        self.router = router
        self.bel = bel
        self.memory = memory
        self.understanding = InputUnderstanding()
        self.context = ContextManager()
        self.reasoning = ReasoningEngine()
        self.planning = PlanningEngine()
        self.decision = DecisionEngine()
        self.response = ResponseEngine()
        self.serious_mode = SeriousModeEngine(router=router)
        self.verification = VerificationEngine()

    async def process_turn(
        self,
        user_text: str,
        request_id: str | None = None,
        project_id: str = "default",
        is_offline: bool = False,
        allow_cloud: bool = True,
    ) -> dict[str, Any]:
        """Process an incoming conversational or operational turn through the cognitive pipeline."""
        req_id = request_id or f"req-{uuid.uuid4().hex[:8]}"

        # 0. Hierarchical Memory Context Retrieval
        memory_citations = []
        memory_context_str = ""
        if self.memory is not None:
            synth = self.memory.synthesize_context(user_text, project_id=project_id)
            memory_context_str = synth.get("context_text", "")
            memory_citations = synth.get("citations", [])

        # 1. Reference Resolution from working context
        context_refs = self.context.resolve_references(user_text)

        # 2. Input Understanding & Intent Classification
        parsed = self.understanding.parse(user_text, context_entities=context_refs)

        # 3. Handle Ambiguity
        if parsed.is_ambiguous and parsed.clarification_prompt:
            clarification_reply = self.response.format_clarification_prompt(parsed.clarification_prompt)
            self.context.add_turn("user", user_text, intent=parsed.intent.value, entities=parsed.entities)
            self.context.add_turn("assistant", clarification_reply)
            return {
                "status": "ok",
                "say": clarification_reply,
                "intent": parsed.intent.value,
                "needs_clarification": True,
                "ambiguity_reason": parsed.ambiguity_reason,
                "requestId": req_id,
            }

        # 4. Handle Serious Mode Deliberation
        if parsed.intent == IntentType.SERIOUS_MODE or parsed.is_serious_mode_requested:
            deliberation = await self.serious_mode.deliberate(user_text)
            self.context.add_turn("user", user_text, intent=IntentType.SERIOUS_MODE.value, entities=parsed.entities)
            self.context.add_turn("assistant", deliberation.final_synthesis)
            return {
                "status": "ok",
                "say": deliberation.final_synthesis,
                "intent": IntentType.SERIOUS_MODE.value,
                "deliberation": deliberation.model_dump(),
                "requestId": req_id,
            }

        # 5. Handle System Queries
        if parsed.intent == IntentType.SYSTEM_QUERY:
            low = user_text.lower().strip()
            if "telemetry" in low or "specs" in low or "hardware" in low:
                from ..system_monitor import monitor
                t = monitor.get_telemetry()
                reply = (
                    f"System Telemetry: Host RAM is at {t['ram']['percent']}% load ({t['ram']['available_mb']} MiB free of {t['ram']['total_mb']} MiB). "
                    f"CPU usage is {t['cpu']['percent']}%. GPU: {t['gpu']['name'] or 'Not detected'} "
                    f"({t['gpu']['free_vram_mb']} MiB VRAM free). Status: {'Safe' if t['safe_for_inference'] else 'Constrained'}."
                )
            else:
                reply = (
                    "BEL's cognitive core is active. I can reason through complex objectives, "
                    "formulate multi-step execution plans, manage your private workspace files, "
                    "and deliberate high-stakes tasks in Serious Mode."
                )
            self.context.add_turn("user", user_text, intent=IntentType.SYSTEM_QUERY.value)
            self.context.add_turn("assistant", reply)
            return {"status": "ok", "say": reply, "intent": IntentType.SYSTEM_QUERY.value, "requestId": req_id}

        # 6. Handle Multi-Step Task Plans
        if parsed.intent == IntentType.TASK_PLAN or len(parsed.sub_instructions) > 1:
            trace = self.reasoning.reason_about_task(user_text, parsed.sub_instructions, parsed.entities)
            plan = self.planning.create_plan(trace, parsed.entities)
            self.context.track_task(task_id=plan.plan_id, goal=plan.goal, total_steps=len(plan.steps))

            step_descriptions = [s.description for s in plan.steps]
            proposal_say = self.response.format_plan_proposal(plan.goal, len(plan.steps), step_descriptions)

            self.context.add_turn("user", user_text, intent=IntentType.TASK_PLAN.value, entities=parsed.entities)
            self.context.add_turn("assistant", proposal_say)

            return {
                "status": "ok",
                "say": proposal_say,
                "intent": IntentType.TASK_PLAN.value,
                "plan": plan.model_dump(),
                "reasoning_trace": trace.model_dump(),
                "outcome": "pending_confirmation",
                "requestId": req_id,
            }

        # 7. Handle Single Tool Action
        if parsed.intent == IntentType.TOOL_ACTION:
            trace = self.reasoning.reason_about_task(user_text, entities=parsed.entities)
            plan = self.planning.create_plan(trace, parsed.entities)
            ready_step = plan.steps[0] if plan.steps else None

            if ready_step and ready_step.tool:
                perm = self.decision.evaluate_permission(ready_step.tool, ready_step.arguments)
                proposal_say = f"I propose to execute '{ready_step.tool}': {ready_step.description}. {perm.reason}"

                self.context.add_turn("user", user_text, intent=IntentType.TOOL_ACTION.value, entities=parsed.entities)
                self.context.add_turn("assistant", proposal_say)

                return {
                    "status": "ok",
                    "say": proposal_say,
                    "intent": IntentType.TOOL_ACTION.value,
                    "tool": ready_step.tool,
                    "arguments": ready_step.arguments,
                    "permission": perm.model_dump(),
                    "outcome": "pending_confirmation" if perm.requires_human_approval else "ready_for_execution",
                    "requestId": req_id,
                }

        # 8. Standard Conversational Intelligence via Task-Aware Model Routing
        route = self.decision.select_route("conversation", is_offline=is_offline, allow_cloud=allow_cloud)
        context_prompt = self.context.get_recent_context_text(max_turns=4)
        if memory_context_str:
            context_prompt = f"{memory_context_str}\n\nRecent Conversation:\n{context_prompt}"

        if self.router is not None:
            try:
                gen_result = await self.router.generate(user_text, local_context=context_prompt)
                answer = gen_result.get("say", "")
                valid, _ = self.verification.validate_model_response(answer)
                if not valid or not answer.strip():
                    answer = "I processed your request, sir. The core system is running and ready for your instruction."
            except Exception as exc:
                answer = self.response.format_failure("inference", str(exc), "Try again or check model status.")
        else:
            if memory_citations:
                cite_tags = ", ".join(c["attribution"] for c in memory_citations[:2])
                answer = f"Understood, sir. Informed by knowledge {cite_tags}. (Processed via {route.provider} route: {route.model_name})."
            else:
                answer = f"Understood, sir. (Processed via {route.provider} route: {route.model_name})."

        self.context.add_turn("user", user_text, intent=IntentType.CONVERSATION.value, entities=parsed.entities)
        self.context.add_turn("assistant", answer)

        return {
            "status": "ok",
            "say": answer,
            "intent": IntentType.CONVERSATION.value,
            "model_route": route.model_dump(),
            "citations": memory_citations,
            "requestId": req_id,
        }
