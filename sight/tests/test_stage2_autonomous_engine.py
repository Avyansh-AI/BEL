"""Stage 2 Verification Tests: Autonomous Execution Engine."""
import asyncio
import time
import pytest

from sight_core.autonomous_engine import (
    AutonomousExecutionEngine,
    AutonomousStepSpec,
    AutonomousTaskRequest,
    AutonomyLevel,
    LifecyclePhase,
)


def test_stage2_full_lifecycle_and_decomposition(tmp_path):
    engine = AutonomousExecutionEngine(tmp_path)
    events = []
    engine.on_notification(lambda n: events.append(n))

    req = AutonomousTaskRequest(goal="collect workspace status then summarize findings")
    progress = engine.submit_task(req)
    assert progress.total_steps == 2
    assert progress.state == "queued"

    final = asyncio.run(engine.run_task(progress.task_id))
    assert final.state == "complete"
    assert final.phase == LifecyclePhase.COMPLETE
    assert final.percent == 100.0
    assert len(final.completion_evidence) == 2
    for phase in ("REQUEST", "UNDERSTAND", "PLAN", "EXECUTE", "OBSERVE", "VERIFY", "COMPLETE"):
        assert phase in final.lifecycle_history
    assert any(e["kind"] == "complete" for e in events)


def test_stage2_parallel_dependency_aware_execution(tmp_path):
    engine = AutonomousExecutionEngine(tmp_path)
    started_times = {}

    async def slow_tool(args, ctx):
        name = args["name"]
        started_times[name] = time.monotonic()
        await asyncio.sleep(0.15)
        return {"tool": name, "status": "ok"}

    def combine_tool(args, ctx):
        outputs = ctx["outputs"]
        return {"combined": [outputs["s1"]["tool"], outputs["s2"]["tool"]], "status": "ok"}

    engine.register_tool("slow.op", slow_tool)
    engine.register_tool("combine.op", combine_tool)

    req = AutonomousTaskRequest(
        goal="Run parallel steps and combine",
        max_parallel=2,
        steps=[
            AutonomousStepSpec(id="s1", description="Branch 1", tool="slow.op", arguments={"name": "a"}),
            AutonomousStepSpec(id="s2", description="Branch 2", tool="slow.op", arguments={"name": "b"}),
            AutonomousStepSpec(id="s3", description="Merge", tool="combine.op", depends_on=["s1", "s2"]),
        ],
    )
    t0 = time.monotonic()
    prog = engine.submit_task(req)
    final = asyncio.run(engine.run_task(prog.task_id))
    elapsed = time.monotonic() - t0

    assert final.state == "complete"
    assert abs(started_times["a"] - started_times["b"]) < 0.1
    assert elapsed < 0.28  # Parallel execution (~0.15s) rather than sequential (~0.30s)
    s3 = next(s for s in final.steps if s.id == "s3")
    assert s3.output["combined"] == ["a", "b"]


def test_stage2_replanning_after_failure(tmp_path):
    engine = AutonomousExecutionEngine(tmp_path)

    def flaky_tool(args, ctx):
        raise RuntimeError("Primary endpoint down")

    def backup_tool(args, ctx):
        return {"recovered": True, "status": "ok"}

    engine.register_tool("primary.op", flaky_tool)
    engine.register_tool("backup.op", backup_tool)

    req = AutonomousTaskRequest(
        goal="Recover via replanning",
        max_replans=2,
        steps=[
            AutonomousStepSpec(
                id="s1",
                description="Try primary then fallback",
                tool="primary.op",
                max_retries=0,
                fallback_tool="backup.op",
            )
        ],
    )
    prog = engine.submit_task(req)
    final = asyncio.run(engine.run_task(prog.task_id))

    assert final.state == "complete"
    assert final.replan_count == 1
    assert "REPLAN" in final.lifecycle_history
    assert final.steps[0].output["recovered"] is True


def test_stage2_restart_recovery_preserves_completed_steps(tmp_path):
    engine1 = AutonomousExecutionEngine(tmp_path)
    calls = {"s1": 0, "s2": 0}

    engine1.register_tool("op.one", lambda a, c: (calls.__setitem__("s1", calls["s1"] + 1) or {"v": 1, "status": "ok"}))
    engine1.register_tool("op.two", lambda a, c: (calls.__setitem__("s2", calls["s2"] + 1) or {"v": 2, "status": "ok"}))

    req = AutonomousTaskRequest(
        goal="Two step persistent task",
        steps=[
            AutonomousStepSpec(id="s1", description="Step 1", tool="op.one"),
            AutonomousStepSpec(id="s2", description="Step 2", tool="op.two", depends_on=["s1"]),
        ],
    )
    prog = engine1.submit_task(req)

    # Simulate s1 completing and s2 interrupted mid-run before restart
    with engine1._connect() as db:
        db.execute("UPDATE autonomous_tasks SET state = 'running' WHERE id = ?", (prog.task_id,))
        db.execute(
            "UPDATE autonomous_steps SET state = 'complete', output_json = '{\"v\": 1}', evidence_json = '{\"verified\": true}' WHERE task_id = ? AND step_id = 's1'",
            (prog.task_id,),
        )
        db.execute("UPDATE autonomous_steps SET state = 'running' WHERE task_id = ? AND step_id = 's2'", (prog.task_id,))

    # New engine instance simulating restart
    engine2 = AutonomousExecutionEngine(tmp_path)
    engine2.register_tool("op.one", lambda a, c: (calls.__setitem__("s1", calls["s1"] + 1) or {"v": 1, "status": "ok"}))
    engine2.register_tool("op.two", lambda a, c: (calls.__setitem__("s2", calls["s2"] + 1) or {"v": 2, "status": "ok"}))

    recovered_count = engine2.recover_interrupted()
    assert recovered_count == 1
    final = asyncio.run(engine2.run_task(prog.task_id))
    assert final.state == "complete"
    assert calls["s1"] == 0  # s1 was NOT re-executed
    assert calls["s2"] == 1  # s2 resumed and completed


def test_stage2_consequential_approval_and_evidence_gate(tmp_path):
    engine = AutonomousExecutionEngine(tmp_path)
    engine.register_tool("danger.op", lambda a, c: {"deleted": False, "status": "ok"}, is_consequential=True)
    engine.register_tool("empty.op", lambda a, c: {}, verifier=lambda out: bool(out.get("proof")))

    req = AutonomousTaskRequest(
        goal="Consequential gate",
        autonomy_level=AutonomyLevel.SUPERVISED,
        steps=[AutonomousStepSpec(id="s1", description="Consequential action", tool="danger.op", is_consequential=True)],
    )
    prog = engine.submit_task(req)
    paused = asyncio.run(engine.run_task(prog.task_id))
    assert paused.state == "awaiting_approval"
    assert paused.phase == LifecyclePhase.AWAITING_APPROVAL

    engine.approve_task(prog.task_id)
    done = asyncio.run(engine.run_task(prog.task_id))
    assert done.state == "complete"

    # Evidence gate rejects empty/unverified output
    req_bad = AutonomousTaskRequest(
        goal="Unverified output",
        max_replans=0,
        steps=[AutonomousStepSpec(id="s1", description="No proof", tool="empty.op", max_retries=0)],
    )
    prog_bad = engine.submit_task(req_bad)
    failed = asyncio.run(engine.run_task(prog_bad.task_id))
    assert failed.state == "failed"


def test_stage2_background_worker_and_cancellation(tmp_path):
    async def _run():
        engine = AutonomousExecutionEngine(tmp_path)
        await engine.start()
        try:
            req1 = AutonomousTaskRequest(goal="Background task")
            p1 = engine.submit_task(req1)
            for _ in range(40):
                st = engine.get_progress(p1.task_id)
                if st.state == "complete":
                    break
                await asyncio.sleep(0.05)
            assert engine.get_progress(p1.task_id).state == "complete"
            assert len(engine.get_notifications(p1.task_id)) >= 1

            req2 = AutonomousTaskRequest(
                goal="Cancel me",
                autonomy_level=AutonomyLevel.MANUAL,
                steps=[AutonomousStepSpec(id="s1", description="Wait", tool="echo.note", arguments={"text": "x"})],
            )
            p2 = engine.submit_task(req2)
            cancelled = engine.cancel_task(p2.task_id)
            assert cancelled.state == "cancelled"
        finally:
            await engine.stop()

    asyncio.run(_run())
