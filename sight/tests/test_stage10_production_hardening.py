"""Stage 10 Verification Tests: Production Hardening & V1 Certification."""
import time
from sight_core.production_hardening import (
    APIKeyRotationManager,
    NetworkEgressGuard,
    PermissionManager,
    SignedUpdateVerifier,
    TamperEvidentAuditLog,
)


def test_stage10_permissions_egress_and_signed_updates():
    pm = PermissionManager()
    pm.grant("code_agent", "code.read")
    assert pm.check("code_agent", "code.read")
    pm.revoke("code_agent", "code.read")
    assert not pm.check("code_agent", "code.read")

    egress = NetworkEgressGuard(allowed_hosts={"api.groq.com"}, allow_loopback=True)
    assert egress.is_allowed("http://127.0.0.1:11434/api/tags")[0]
    assert egress.is_allowed("https://api.groq.com/openai/v1/chat/completions")[0]
    assert not egress.is_allowed("http://169.254.169.254/latest/meta-data")[0]
    assert not egress.is_allowed("https://evil.example.com/exfiltrate")[0]

    verifier = SignedUpdateVerifier(b"bel_release_signing_key")
    payload = b"BEL-v1.0.0-release-bundle"
    sig = verifier.sign_payload(payload)
    assert verifier.verify_payload(payload, sig)
    assert not verifier.verify_payload(b"tampered-bundle", sig)


def test_stage10_tamper_evident_audit_log_and_key_rotation(tmp_path):
    log = TamperEvidentAuditLog(tmp_path / "audit.jsonl")
    log.append("manager_agent", "task.start", {"task_id": "t1"})
    log.append("security_agent", "scan.pass", {"findings": 0})
    ok, err = log.verify_chain()
    assert ok and err is None

    # Tamper with record 1
    raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    (tmp_path / "audit.jsonl").write_text(raw.replace("t1", "t999"), encoding="utf-8")
    ok_tampered, err_tampered = log.verify_chain()
    assert not ok_tampered and "Tampered" in err_tampered

    rot = APIKeyRotationManager(max_age_days=30)
    rot.record_key("groq", "fp_old", created_at=time.time() - 40 * 86400)
    assert rot.needs_rotation("groq")
    rot.rotate("groq", "fp_new")
    assert not rot.needs_rotation("groq")
