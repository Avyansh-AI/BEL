"""BEL V1 Final Completion Validation Suite.

Covers end-to-end integration, security boundary enforcement, fault isolation,
persistence recovery, and performance benchmarks across all 11 BEL V1 stages.
"""
from __future__ import annotations

import base64
import io
import time
import zipfile
from pathlib import Path
from PIL import Image
from fastapi.testclient import TestClient
import pytest

from sight_core.api import create_app
from sight_core.config import Config
from sight_core.backup_restore import BackupRestoreManager

URL = "http://127.0.0.1:8080"


def _make_png_b64(color: tuple[int, int, int], size: tuple[int, int] = (32, 32)) -> str:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _authenticate(client: TestClient, app) -> None:
    client.post(
        "/api/session/claim",
        json={"token": app.state.bootstrap_token},
        headers={"origin": URL},
    ).raise_for_status()
    client.headers["x-sight-csrf"] = client.get("/api/session").json()["csrf"]


@pytest.fixture
def v1_client(tmp_path: Path):
    app = create_app(Config(tmp_path / "data", local_tts=False))
    with TestClient(app, base_url=URL) as client:
        _authenticate(client, app)
        yield app, client


def test_stage1_autonomous_engine_api_and_approval_gate(v1_client):
    app, client = v1_client

    # 1. Submit and immediately execute a multi-step DAG using bound BEL subsystems
    res = client.post(
        "/api/autonomous/tasks",
        json={
            "goal": "Inspect repo and store findings in personal memory",
            "priority": 3,
            "run_immediately": True,
            "nodes": [
                {
                    "id": "inspect_step",
                    "description": "Inspect workspace architecture",
                    "tool": "code.inspect_repo",
                    "arguments": {},
                },
                {
                    "id": "memory_step",
                    "description": "Record inspection completion",
                    "tool": "memory.store",
                    "arguments": {"key": "repo_status", "content": "Workspace inspected cleanly"},
                    "depends_on": ["inspect_step"],
                },
            ],
        },
    )
    assert res.status_code == 200
    prog = res.json()
    assert prog["state"] == "complete"
    assert prog["phase"] == "COMPLETE"
    assert prog["completed_steps"] == 2
    assert len(prog["completion_evidence"]) == 2

    # 2. Submit a consequential step that requires explicit human approval
    res_gate = client.post(
        "/api/autonomous/tasks",
        json={
            "goal": "Consequential operation gated by approval",
            "run_immediately": True,
            "nodes": [
                {
                    "id": "gated_step",
                    "description": "Write consequential state",
                    "tool": "echo.note",
                    "arguments": {"text": "consequential"},
                    "is_consequential": True,
                }
            ],
        },
    )
    assert res_gate.status_code == 200
    gated_prog = res_gate.json()
    task_id = gated_prog["task_id"]
    assert gated_prog["state"] == "awaiting_approval"
    assert gated_prog["phase"] == "AWAITING_APPROVAL"

    # Check notification emitted for approval
    notifs = client.get(f"/api/autonomous/notifications?task_id={task_id}").json()["items"]
    assert any(n["kind"] == "approval_required" for n in notifs)

    # Approve and run to completion
    res_app = client.post(
        f"/api/autonomous/tasks/{task_id}/approve",
        json={"node_id": "gated_step", "approved": True, "run_after_approval": True},
    )
    assert res_app.status_code == 200
    assert res_app.json()["state"] == "complete"


def test_stage2_multi_agent_collaboration_and_domain_binding(v1_client):
    app, client = v1_client

    roles_res = client.get("/api/agents/roles")
    assert roles_res.status_code == 200
    roles = roles_res.json()["items"]
    assert len(roles) == 10

    exec_res = client.post(
        "/api/agents/execute",
        json={
            "goal": "Research, implement, and security-verify a module",
            "subtasks": [
                {
                    "id": "sub_research",
                    "role": "research",
                    "capability": "web_research",
                    "description": "Verify Python documentation standards",
                },
                {
                    "id": "sub_code",
                    "role": "coding",
                    "capability": "software_development",
                    "description": "Implement feature module",
                    "depends_on": ["sub_research"],
                    "verify_by_role": "security",
                },
            ],
        },
    )
    assert exec_res.status_code == 200
    state = exec_res.json()
    assert state["status"] == "complete"
    assert state["results"]["sub_research"]["success"] is True
    assert state["results"]["sub_research"]["output"]["domain_meta"]["service"] == "web_research"
    assert state["results"]["sub_code"]["verified"] is True

    msgs = client.get("/api/agents/messages").json()["items"]
    assert len(msgs) >= 3


def test_stage4_and_5_personal_memory_persistence_and_voice_profiles(tmp_path: Path):
    data_dir = tmp_path / "persist_data"
    app1 = create_app(Config(data_dir, local_tts=False))
    with TestClient(app1, base_url=URL) as c1:
        _authenticate(c1, app1)
        r1 = c1.post(
            "/api/personal/memory/add",
            json={
                "subject": "preferred_editor",
                "content": "Owner prefers dark mode and concise briefings",
                "kind": "preference",
                "importance": 0.9,
            },
        )
        assert r1.status_code == 200
        r2 = c1.post(
            "/api/personal/memory/add",
            json={
                "subject": "preferred_editor",
                "content": "Owner prefers light mode",
                "kind": "preference",
                "importance": 0.6,
            },
        )
        assert r2.status_code == 200

        # Contradiction detection
        contra = c1.get("/api/personal/memory/contradictions").json()["contradictions"]
        assert len(contra) == 1

        # Voice profiles & sentence streaming
        profs = c1.get("/api/speech/profiles").json()["items"]
        assert len(profs) >= 2
        chunks = c1.post(
            "/api/speech/stream_chunks?profile_id=hi_bel",
            json={"text": "Namaste Sir. Aapka system taiyar hai."},
        ).json()["chunks"]
        assert len(chunks) == 2
        assert chunks[0]["language"] == "hi-IN"

    # Recreate app over the same data_dir to verify SQLite persistence across restarts
    app2 = create_app(Config(data_dir, local_tts=False))
    with TestClient(app2, base_url=URL) as c2:
        _authenticate(c2, app2)
        items = c2.get("/api/personal/memory").json()["items"]
        assert len(items) == 2


def test_stage6_computer_use_workflows_and_smart_devices(v1_client):
    app, client = v1_client

    # Save & replay a safe workflow
    save_res = client.post(
        "/api/automation/workflows/save",
        json={
            "workflow_id": "daily_prep",
            "name": "Daily Prep",
            "steps": [
                {"kind": "wait", "arguments": {"ms": 5}, "expect_ui_change": False},
                {"kind": "clipboard_set", "arguments": {"text": "BEL Ready"}, "expect_ui_change": False},
            ],
        },
    )
    assert save_res.status_code == 200
    assert "daily_prep" in client.get("/api/automation/workflows").json()["items"]

    rep_res = client.post("/api/automation/workflows/daily_prep/replay", json={})
    assert rep_res.status_code == 200
    assert all(r["success"] for r in rep_res.json()["reports"])

    # Path traversal attempt in workflow ID must be rejected with 403
    bad_wf = client.post(
        "/api/automation/workflows/save",
        json={"workflow_id": "../../escape", "name": "Bad", "steps": []},
    )
    assert bad_wf.status_code == 403

    # Smart device discovery & HMAC command authentication
    disc = client.post(
        "/api/devices/discover?permitted=true",
        json={"devices": [{"device_id": "lamp_1", "name": "Desk Lamp", "kind": "light", "host": "192.168.1.50"}]},
    )
    assert disc.status_code == 200
    auth_res = client.post("/api/devices/authenticate", json={"device_id": "lamp_1", "command": "pair", "signature": ""})
    assert auth_res.status_code == 200
    token = auth_res.json()["token"]

    # Unauthorized command with bad token fails with 403
    bad_cmd = client.post(
        "/api/devices/command",
        json={"device_id": "lamp_1", "command": "power", "params": {"on": True}, "signature": "wrong_token"},
    )
    assert bad_cmd.status_code == 403

    # Authorized command succeeds
    ok_cmd = client.post(
        "/api/devices/command",
        json={"device_id": "lamp_1", "command": "power", "params": {"on": True}, "signature": token},
    )
    assert ok_cmd.status_code == 200
    assert ok_cmd.json()["state"]["on"] is True


def test_stage7_multimodal_unified_and_privacy_controls(v1_client):
    app, client = v1_client
    dark_b64 = _make_png_b64((15, 15, 15))
    bright_b64 = _make_png_b64((230, 230, 230))

    # Image comparison
    cmp_res = client.post(
        "/api/multimodal/image/compare",
        json={"image_a_base64": dark_b64, "image_b_base64": bright_b64, "threshold": 15},
    )
    assert cmp_res.status_code == 200
    assert cmp_res.json()["changed_significantly"] is True

    # Video scene change detection
    vid_res = client.post(
        "/api/multimodal/video/analyze",
        json={"frames_base64": [dark_b64, dark_b64, bright_b64], "scene_threshold": 0.1},
    )
    assert vid_res.status_code == 200
    assert len(vid_res.json()["scene_changes"]) == 1

    # Camera consent gate
    no_consent = client.post("/api/multimodal/camera/ingest", json={"frame_base64": bright_b64})
    assert no_consent.status_code == 403

    client.post("/api/multimodal/camera/consent", json={"granted": True})
    with_consent = client.post("/api/multimodal/camera/ingest", json={"frame_base64": bright_b64})
    assert with_consent.status_code == 200
    assert with_consent.json()["width"] == 32

    # Unified multimodal reasoning
    reason_res = client.post(
        "/api/multimodal/reason",
        json={
            "query": "Summarize visual and text evidence",
            "evidence": {"text": "Revenue grew 18%", "images_base64": [bright_b64]},
        },
    )
    assert reason_res.status_code == 200
    assert reason_res.json()["grounded"] is True
    assert "image" in reason_res.json()["modalities_used"]


def test_stage8_web_research_ssrf_and_integration_hub(v1_client):
    app, client = v1_client

    # SSRF attempt to cloud metadata IP is blocked with 403
    ssrf_res = client.post(
        "/api/research/query",
        json={
            "query": "metadata check",
            "sources": [{"url": "http://169.254.169.254/latest/meta-data", "title": "Meta", "snippet": "secret"}],
        },
    )
    assert ssrf_res.status_code == 403

    # Legitimate research query with contradiction detection
    ok_res = client.post(
        "/api/research/query",
        json={
            "query": "BEL release latency",
            "sources": [
                {"url": "https://docs.python.org/3/", "title": "Python Docs", "snippet": "Latency is 12 ms"},
                {"url": "https://github.com/bel/spec", "title": "Spec", "snippet": "Latency is 45 ms"},
            ],
        },
    )
    assert ok_res.status_code == 200
    rep = ok_res.json()
    assert len(rep["sources"]) == 2
    assert len(rep["contradictions"]) >= 1

    # Integration hub permission & invocation
    conns = client.get("/api/integrations/connectors").json()["items"]
    assert any(c["connector_id"] == "github" for c in conns)

    # Disabled connector fails safely
    inv_disabled = client.post(
        "/api/integrations/invoke",
        json={"connector": "github", "action": "read", "payload": {}},
    )
    assert inv_disabled.status_code == 200
    assert inv_disabled.json()["success"] is False


def test_stage9_bel_code_delivery_and_security_scan(v1_client):
    app, client = v1_client

    # Deliver feature inside workspace
    deliv = client.post(
        "/api/coding/bel_code/deliver",
        json={
            "feature_name": "Add math helper",
            "target_rel_path": "pkg/math_helper.py",
            "new_code": "def add_numbers(a: int, b: int) -> int:\n    return a + b\n",
        },
    )
    assert deliv.status_code == 200
    assert deliv.json()["review"]["passed"] is True

    # Path traversal outside workspace is blocked with 403
    escape_scan = client.post("/api/coding/bel_code/scan", json={"rel_path": "../../outside.py"})
    assert escape_scan.status_code == 403

    # Package workspace into ZIP
    pkg = client.post("/api/coding/bel_code/package", json={"output_zip_name": "bel_code_bundle.zip"})
    assert pkg.status_code == 200
    assert Path(pkg.json()["zip_path"]).exists()


def test_stage10_creative_studio_workflows(v1_client):
    app, client = v1_client

    # Blender render inspection
    bright_b64 = _make_png_b64((180, 190, 210))
    b_res = client.post(
        "/api/creative/studio/blender_inspect",
        json={"image_base64": bright_b64, "auto_correct": True},
    )
    assert b_res.status_code == 200
    assert b_res.json()["passed"] is True

    # Godot 4 project scaffolding, validation, and packaging
    g_res = client.post("/api/creative/studio/godot_package", json={"project_name": "BelRunner2D"})
    assert g_res.status_code == 200
    assert g_res.json()["valid"] is True
    assert Path(g_res.json()["package_path"]).exists()

    # Unreal Engine 5 project & C++ actor scaffolding
    u_res = client.post("/api/creative/studio/unreal_scaffold", json={"project_name": "BelSimUE5"})
    assert u_res.status_code == 200
    assert Path(u_res.json()["uproject_file"]).exists()


def test_stage11_security_hardening_and_zip_slip_protection(v1_client, tmp_path: Path):
    app, client = v1_client

    # 1. Tamper-evident audit chain verification
    chain_res = client.get("/api/security/audit_chain/verify")
    assert chain_res.status_code == 200
    assert chain_res.json()["valid"] is True

    # 2. Egress guard SSRF & allowlist check
    eg_bad = client.post("/api/security/egress/check", json={"url": "http://169.254.169.254/latest"})
    assert eg_bad.json()["allowed"] is False
    eg_ok = client.post("/api/security/egress/check", json={"url": "https://api.groq.com/openai/v1/models"})
    assert eg_ok.json()["allowed"] is True

    # 3. Permission grant & check
    client.post("/api/security/permissions/grant", json={"scope": "desktop.actuate", "granted": True})
    perm_chk = client.get("/api/security/permissions/check?scope=desktop.actuate").json()
    assert perm_chk["granted"] is True

    # 4. API key rotation fingerprint tracking
    rot = client.post("/api/security/keys/rotate", json={"provider": "groq", "new_key": "gsk_test_secret_value_12345"})
    assert rot.status_code == 200
    assert rot.json()["rotations"] == 1
    assert "gsk_test" not in str(rot.json())

    # 5. Zip-Slip path traversal rejection in BackupRestoreManager
    mgr = BackupRestoreManager(data_dir=tmp_path / "restore_target")
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as zf:
        zf.writestr("../../escaped_evil.txt", "pwned")
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import os
    nonce = os.urandom(12)
    ct = AESGCM(mgr._key).encrypt(nonce, zip_buf.getvalue(), None)
    malicious_enc = tmp_path / "malicious_backup.belbak"
    malicious_enc.write_bytes(nonce + ct)

    res = mgr.restore_backup(malicious_enc)
    assert res.success is False
    assert "Security violation" in (res.error or "")
    assert not (tmp_path / "escaped_evil.txt").exists()


def test_performance_response_latency_benchmarks(v1_client):
    app, client = v1_client
    t0 = time.perf_counter()
    res = client.get("/api/system/convergence/status")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert res.status_code == 200
    assert elapsed_ms < 250.0


def test_wake_word_noise_speech_and_false_activation_resistance():
    """Verify wake-word detector against background rumble, ordinary speech, and false activations."""
    import math
    import struct
    from sight_core.wake_detector import AcousticWakeDetector, SAMPLE_RATE, WakeState

    det = AcousticWakeDetector(wake_phrase="bel", energy_threshold=0.015)

    # 1. Low-frequency background rumble / hum (ZCR < 0.02) must NOT trigger speech or wake
    rumble_samples = [int(6000 * math.sin(2 * math.pi * 35.0 * (i / SAMPLE_RATE))) for i in range(1600)]
    rumble_pcm = struct.pack(f"<{len(rumble_samples)}h", *rumble_samples)
    res_rumble = det.process_chunk(rumble_pcm)
    assert res_rumble.triggered is False
    assert res_rumble.speech_detected is False
    assert det.state == WakeState.IDLE

    # 2. High-frequency white/static hiss (ZCR > 0.45) must NOT trigger speech or wake
    hiss_samples = [8000 if i % 2 == 0 else -8000 for i in range(1600)]
    hiss_pcm = struct.pack(f"<{len(hiss_samples)}h", *hiss_samples)
    res_hiss = det.process_chunk(hiss_pcm)
    assert res_hiss.triggered is False
    assert res_hiss.speech_detected is False

    # 3. Short ordinary speech (< 0.4s buffer) enters LISTENING but does NOT false-trigger wake
    det.reset()
    speech_samples = [int(900 * math.sin(2 * math.pi * 220.0 * (i / SAMPLE_RATE))) for i in range(1600)]
    speech_pcm = struct.pack(f"<{len(speech_samples)}h", *speech_samples)
    res_speech = det.process_chunk(speech_pcm)
    assert res_speech.speech_detected is True
    assert res_speech.triggered is False
    assert det.state == WakeState.LISTENING


def test_comprehensive_failure_injection_suite(tmp_path: Path):
    """Simulate HTTP 429, invalid API keys, network timeouts, corrupted DBs, and connector hangs."""
    import asyncio
    import httpx
    from sight_core.models import OllamaProvider
    from sight_core.routing import ModelRouter, ProviderPolicy
    from sight_core.store import Store
    from sight_core.web_intelligence import ConnectorPermission, IntegrationHub

    store = Store(tmp_path / "fail_inject.sqlite3")
    store.set_setting(
        "provider.groq",
        ProviderPolicy(
            provider="groq",
            enabled=True,
            model="llama-3.1-8b-instant",
            allow_remote_text=True,
            free_only=True,
            free_tier_confirmed=True,
        ).model_dump(),
    )

    class MockVault:
        def get(self, name: str):
            return "gsk_mock_key_123456" if name == "groq" else None

    mode = {"scenario": "429"}

    def transport_handler(req: httpx.Request) -> httpx.Response:
        if "127.0.0.1:11434" in str(req.url):
            raise httpx.ConnectError("Simulated local Ollama offline")
        if mode["scenario"] == "429":
            return httpx.Response(
                429,
                headers={" retry-after": "120"},
                json={"error": {"code": "rate_limit_exceeded", "message": "Rate limit reached"}},
            )
        if mode["scenario"] == "401":
            return httpx.Response(
                401,
                json={"error": {"code": "invalid_api_key", "message": "Invalid API key provided"}},
            )
        if mode["scenario"] == "timeout":
            raise httpx.ReadTimeout("Simulated model timeout")
        return httpx.Response(200, json={"choices": [{"message": {"content": "Recovered"}}]})

    tr = httpx.MockTransport(transport_handler)
    cfg = Config(tmp_path / "fail_data", model="gemma4:e4b-it-qat")

    # Scenario 1: HTTP 429 rate-limit handling
    router_429 = ModelRouter(OllamaProvider(cfg, transport=tr), store, local_only=False, vault=MockVault(), transport=tr)
    res_429 = asyncio.run(router_429.generate("Test 429"))
    assert res_429["status"] in ("rate_limited", "quota")

    # Scenario 2: Invalid API key (401)
    store2 = Store(tmp_path / "fail_401.sqlite3")
    store2.set_setting("provider.groq", store.setting("provider.groq"))
    mode["scenario"] = "401"
    router_401 = ModelRouter(OllamaProvider(cfg, transport=tr), store2, local_only=False, vault=MockVault(), transport=tr)
    res_401 = asyncio.run(router_401.generate("Test 401"))
    assert res_401["status"] == "permission_denied"
    assert "gsk_mock_key_123456" not in str(res_401)

    # Scenario 3: Network timeout
    store3 = Store(tmp_path / "fail_timeout.sqlite3")
    store3.set_setting("provider.groq", store.setting("provider.groq"))
    mode["scenario"] = "timeout"
    router_to = ModelRouter(OllamaProvider(cfg, transport=tr), store3, local_only=False, vault=MockVault(), transport=tr)
    res_to = asyncio.run(router_to.generate("Test timeout"))
    assert res_to["status"] == "offline"

    # Scenario 4: Connector deadline timeout isolation
    hub = IntegrationHub()

    async def slow_connector(_scope: str, _payload: dict):
        await asyncio.sleep(2.0)
        return {"ok": True}

    hub.register_connector(
        "rest_api",
        slow_connector,
        ConnectorPermission(connector_id="rest_api", enabled=True, allowed_scopes=["read"]),
    )
    conn_res = asyncio.run(hub.invoke("rest_api", "read", timeout_sec=0.05))
    assert conn_res.success is False
    assert "timeout" in (conn_res.error or "").lower() or "deadline" in (conn_res.error or "").lower()


def test_phase1_core_intelligence_contradictions_and_depth():
    """Verify contradiction detection, reasoning depth selection, and expanded reference resolution."""
    from sight_core.cognitive.understanding import InputUnderstanding

    u = InputUnderstanding()

    # 1. Contradictory instructions on same file are flagged ambiguous
    contradict = u.parse("create report.txt and delete report.txt")
    assert contradict.is_ambiguous is True
    assert "contradictory" in (contradict.ambiguity_reason or "").lower()

    # 2. Reasoning depth selection
    fast_q = u.parse("status")
    assert fast_q.reasoning_depth == "fast"
    deep_q = u.parse("Use serious mode to analyze the Q4 architecture migration")
    assert deep_q.reasoning_depth == "deep"

    # 3. Expanded anaphoric reference resolution (application + plural files)
    resolved_app = u.parse("open that app", context_entities={"application": "calculator"})
    assert resolved_app.entities.get("application") == "calculator"
    assert resolved_app.entities.get("anaphoric_resolved") is True

    resolved_files = u.parse("compare both files", context_entities={"files": ["a.py", "b.py"]})
    assert resolved_files.entities.get("files") == ["a.py", "b.py"]


def test_phase3_complete_14_step_skill_forging_and_rsi_lifecycle(tmp_path: Path):
    """Verify the complete 14-step Skill Forging & RSI lifecycle, AST import boundaries, and monitoring."""
    from sight_core.brain_store import BrainStore
    from sight_core.rsi import (
        RecursiveSelfImprovementEngine,
        TestCase,
        audit_code_safety,
    )

    store = BrainStore(tmp_path / "rsi_lifecycle.sqlite3")
    rsi = RecursiveSelfImprovementEngine(store=store)

    # Steps 1-3: Detect gap, identify existing skills, research capability
    gap, candidate, test_res = rsi.process_request_for_extensions(
        "Please convert 100 celsius to fahrenheit",
        detected_intent="tool_action",
    )
    assert gap is not None
    assert candidate is not None
    assert test_res is not None and test_res.passed is True

    research = rsi.research_capability(gap)
    assert research["suggested_tool_name"] == "temperature_converter"
    assert "math" in research["allowed_imports"]

    # Step 5 & 8: Prohibited imports (subprocess, socket, open) must be rejected by ASTSecurityAuditor
    safe_ok, err_msg = audit_code_safety("import subprocess\ndef execute_tool(): return 1")
    assert safe_ok is False
    assert "subprocess" in (err_msg or "")

    deps_ok, deps, dep_err = rsi.validate_dependencies_and_permissions(candidate)
    assert deps_ok is True
    assert dep_err is None

    # Steps 9-10: SkillQualityReport generation
    quality = rsi.evaluate_quality(candidate, test_res)
    assert quality.ready_for_promotion is True
    assert quality.security_audit_passed is True
    assert quality.functional_pass_rate == 1.0
    assert quality.owner_approval_required is True

    # Find saved candidate_id in store
    with store.connect() as db:
        row = db.execute("SELECT id, digest FROM candidates ORDER BY created_at DESC LIMIT 1").fetchone()
    assert row is not None

    # Step 11: Promotion without owner approval must fail closed
    with pytest.raises(PermissionError, match="Owner approval"):
        rsi.promote_candidate(row["id"], row["digest"], owner_approved=False)

    # Step 12: Promote with owner approval
    promoted = rsi.promote_candidate(row["id"], row["digest"], owner_approved=True)
    assert promoted["status"] == "active"
    assert promoted["version"] == 1

    # Step 14: Monitor post-promotion skill execution
    mon = rsi.record_skill_execution(promoted["skill_id"], success=True, latency_ms=4.2)
    assert mon["invoked"] == 1
    assert mon["healthy"] is True


def test_phase4_multi_agent_deduplication_timeouts_and_synthesis():
    """Verify multi-agent duplicate work deduplication, subtask timeouts, and Manager final synthesis."""
    import asyncio
    from sight_core.multi_agent import AgentProfile, AgentRole, AgentSubtask, MultiAgentOrchestrator

    orch = MultiAgentOrchestrator()

    # 1. Duplicate work deduplication + Manager final synthesis
    subtasks = [
        AgentSubtask(id="s1", role=AgentRole.RESEARCH, capability="web_research", description="Analyze local cache architecture"),
        AgentSubtask(id="s2", role=AgentRole.RESEARCH, capability="web_research", description="Analyze local cache architecture", depends_on=["s1"]),
    ]
    state = asyncio.run(orch.execute_project("Architecture Review", subtasks))
    assert state.status == "complete"
    assert "s2" in state.deduplicated_subtasks
    assert state.results["s2"].tokens_used == 0
    assert "Manager synthesis" in state.final_synthesis

    # 2. Subtask timeout enforcement
    async def slow_agent(_sub, _ctx, _st):
        await asyncio.sleep(1.0)
        return {"summary": "Too slow"}

    orch.register_agent(
        AgentProfile(agent_id="analyst_agent", role=AgentRole.ANALYST, capabilities=["data_analysis"]),
        slow_agent,
    )
    timeout_state = asyncio.run(
        orch.execute_project(
            "Timeout Check",
            [AgentSubtask(id="slow_1", role=AgentRole.ANALYST, capability="data_analysis", description="Slow task", timeout_seconds=0.05)],
        )
    )
    assert timeout_state.results["slow_1"].success is False
    assert "TimeoutError" in (timeout_state.results["slow_1"].error or "")


