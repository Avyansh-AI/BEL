# BEL (Behavioral Executive Logic) — Release Acceptance Matrix

This document defines the formal verification criteria required before any release candidate is promoted to production (`v1.0.0`).

---

## 1. Acceptance Gates

| Gate ID | Area | Acceptance Criterion | Verification Method | Status |
| :---: | :--- | :--- | :--- | :---: |
| **SEC-01** | Security | All credentials redacted from logs and history | `test_history_bounded_persistent_redacted` | **PASSED** |
| **SEC-02** | Security | Model cannot grant itself tool execution permissions | `test_model_cannot_grant_itself_permission` | **PASSED** |
| **SEC-03** | Security | Win32 exclusive file lock held during file mutations | `test_edit_excludes_concurrent_owner_write` | **PASSED** |
| **SEC-04** | Security | Single-use action approval tokens cannot be replayed | `test_review_api_enforces_grant_and_history_clear` | **PASSED** |
| **SEC-05** | Security | Subprocess workers run with `-I -S` isolation | `test_source_worker_keeps_isolation` | **PASSED** |
| **SYS-01** | Hardware | System monitor tracks host RAM, CPU, and VRAM | `test_system_monitor_telemetry` | **PASSED** |
| **SYS-02** | Hardware | Refuses heavy local inference if RAM < 300 MiB | `test_memory_safety_check_load_shedding` | **PASSED** |
| **MEM-01** | Memory | Ephemeral memories respect TTL expiration | `test_expired_source_disables_summary_without_purge` | **PASSED** |
| **MEM-02** | Memory | Database backup/restore preserves owner ID & hashes | `test_backup_restore_hash_migration_and_corruption` | **PASSED** |
| **MEM-03** | Memory | Context pre-compression creates memory checkpoint | `test_watermark_triggers_automatic_checkpoint` | **PASSED** |
| **VOX-01** | Voice | 16kHz mono PCM capture capped at 20 seconds | `twenty-second capture cap stops input` | **PASSED** |
| **VOX-02** | Voice | Offline Whisper C++ ASR transcribes local WAV | `test_speech_engines.py` | **PASSED** |
| **VOX-03** | Voice | Offline TTS synthesizes natural audio output | `test_speech_synthesize_offline` | Planned (Stage 3.2) |
| **UI-01** | Interface | 3D Particle Wave Sphere responds to audio waveform | `Orb.tsx` WebGL / Canvas visual rendering | **PASSED** |
| **UI-02** | Interface | Frontend build produces zero TypeScript errors | `npm run build` | **PASSED** |
| **APP-01** | Desktop | App launch restricted to allowlisted executables | `test_windows_apps.py` | **PASSED** |
| **APP-02** | Desktop | Background mode requires working system tray | `test_background_requires_working_tray` | **PASSED** |
| **REL-01** | Release | All automated tests pass with 0 failures | 384 / 384 automated tests passing | **PASSED** |

---

## 2. Sign-Off Authorization

- **Baseline Audit Version:** `v0.5.0`
- **Current Milestone:** Stage 1, Stage 2 (Item 2.1), Stage 3 (Item 3.1) Implemented and Verified
- **Target Production Version:** `v1.0.0`
- **Next Stage Target:** Stage 3.2 (Offline Speech Synthesis via Piper/Sherpa-ONNX)
