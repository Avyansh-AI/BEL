# BEL V1 — Security & Privacy Audit Report
**Date:** November 12, 2026  
**Scope:** Full BEL V1 Backend (`sight/sight_core/`), Frontend (`frontend/`), and Packaging Scripts (`sight/scripts/`)

---

## 1. Security Posture Summary

BEL V1 enforces a strict local-first, owner-controlled security architecture governed by **Axiom 1** (*Human life, safety, and dignity strictly supersede AI continuity*). All network surfaces, file operations, tool executions, and external connectors operate under defense-in-depth boundaries.

| Security Domain | Mechanism Implemented | Verification Test | Status |
|---|---|---|---|
| **HTTP / WebSocket Authentication** | Owner bootstrap token (`browser-token`), HTTP-only session cookie (`sight_session`), `x-sight-csrf` header validation on all state-mutating requests, strict `Host` & `Origin` loopback checks | `test_bel.py`, `test_bel_v1_validation_suite.py` | **VERIFIED** |
| **Immutable Safety Kernel (Axiom 1)** | `PROTECTED_CORE_FILES` (`api.py`, `safety.py`, `security.py`, `store.py`, `boundaries.py`, `sandbox.py`) protected against RSI self-modification and audited via SHA-256 manifest | `test_rsi.py`, `test_stage10_convergence.py` | **VERIFIED** |
| **Secret Storage & Log Redaction** | Windows DPAPI hardware-backed encryption (`DPAPIVault` via `CryptProtectData`), automatic credential redaction (`redact()`, `redact_transport_logs()`), key fingerprint tracking without storing raw secrets (`APIKeyRotationManager`) | `test_vault_dpapi.py`, `test_bel_v1_validation_suite.py` | **VERIFIED** |
| **SSRF & Network Egress Protection** | `NetworkEgressGuard` + `WebResearchEngine.is_safe_url()` + `BrowserAutomationService` block non-HTTP(S) schemes, RFC1918 private networks, loopback (unless explicitly permitted), link-local, and cloud metadata IPs (`169.254.169.254`) | `test_stage10_production_hardening.py`, `test_bel_v1_validation_suite.py` | **VERIFIED** |
| **Workspace & Archive Path Containment** | `LocalFiles`, `BELCodeAgent._resolve_workspace_path()`, `WorkflowRecorder._safe_workflow_path()`, and `BackupRestoreManager.restore_backup()` enforce `Path.resolve().relative_to(base_dir)` and reject `..` / Zip-Slip payloads | `test_backup_restore.py`, `test_bel_v1_validation_suite.py` | **VERIFIED** |
| **Consequential Action Approval Gates** | Two-phase prepare/consume approval tokens (`/api/actions/prepare`), `AutonomousExecutionEngine` consequential step gate (`AWAITING_APPROVAL`), `ComputerUseOrchestrator` consequential action check, and hotkey blacklist (`Alt+F4`, `Ctrl+Alt+Del`, `Win+L`, `Format`) | `test_actuator.py`, `test_stage2_autonomous_engine.py`, `test_bel_v1_validation_suite.py` | **VERIFIED** |
| **Privacy & Biometric Controls** | Microphone, camera (`CameraContextService`), and speaker ID (`SpeakerIdentifier`) are opt-in/disabled by default; instant speaker voiceprint purge (`/api/speech/speaker/purge`); voice is never accepted as authority for privileged actions (`409` / `403`) | `test_speech.py`, `test_stage5_multimodal.py`, `test_bel_v1_validation_suite.py` | **VERIFIED** |
| **Tamper-Evident Audit Trail** | Every `audit()` event is written to SQLite, rotating logs, and the SHA-256 hash-chained `TamperEvidentAuditLog` (`tamper_evident_audit.jsonl`), verifiable via `/api/security/audit_chain/verify` | `test_stage10_production_hardening.py`, `test_bel_v1_validation_suite.py` | **VERIFIED** |

---

## 2. Vulnerabilities Discovered & Remediated During V1 Audit

### VULN-01: Zip-Slip Arbitrary File Overwrite in `BackupRestoreManager.restore_backup()`
- **Severity:** High
- **Location:** [backup_restore.py](file:///c:/Users/Dell/Documents/Ai%20projects/BEL/sight/sight_core/backup_restore.py#L138-L168)
- **Finding:** After AES-GCM decryption, `restore_backup()` iterated over `zf.namelist()` and wrote `(self.data_dir / member)` without verifying that `member` did not contain `..` or absolute paths.
- **Fix:** Added a strict pre-extraction validation pass rejecting any archive member containing `..`, `.`, `:`, leading `/`, or resolving outside `self.data_dir.resolve()`. Verified by `test_stage11_security_hardening_and_zip_slip_protection`.

### VULN-02: Path Traversal in `WorkflowRecorder` (`save` / `load`)
- **Severity:** Medium
- **Location:** [computer_use.py](file:///c:/Users/Dell/Documents/Ai%20projects/BEL/sight/sight_core/computer_use.py#L138-L158)
- **Finding:** `workflow_id` was interpolated directly into `self.storage_dir / f"{workflow_id}.json"`.
- **Fix:** Added `_safe_workflow_path()` rejecting path separators, `..`, and colons, and verifying containment inside `self.storage_dir`. Returns HTTP `403` on `/api/automation/workflows/save` and `/replay`.

### VULN-03: Path Traversal in `BELCodeAgent.scan_vulnerabilities()` and Session Persistence
- **Severity:** Medium
- **Location:** [bel_code.py](file:///c:/Users/Dell/Documents/Ai%20projects/BEL/sight/sight_core/bel_code.py#L144-L168)
- **Finding:** `scan_vulnerabilities(rel_paths)` and `save_session()`/`load_session()` did not verify that supplied relative paths or session IDs stayed inside `self.workspace_root` / `self.session_dir`.
- **Fix:** Added `_resolve_workspace_path()` and `_safe_session_path()` raising `PermissionError` (mapped to HTTP `403`) on any escape attempt.

### VULN-04: SSRF & Unbounded Connector Wait in `WebResearchEngine` / `IntegrationHub`
- **Severity:** Medium
- **Location:** [web_intelligence.py](file:///c:/Users/Dell/Documents/Ai%20projects/BEL/sight/sight_core/web_intelligence.py#L120-L137)
- **Finding:** `WebResearchEngine` did not filter private/metadata URLs in source lists, and `IntegrationHub.invoke()` awaited async connector handlers without a deadline timeout.
- **Fix:** Added `WebResearchEngine.is_safe_url()` blocking private/loopback/link-local/metadata IPs (`169.254.169.254`) and wrapped `IntegrationHub.invoke()` in `asyncio.wait_for(..., timeout=timeout_sec)`.
