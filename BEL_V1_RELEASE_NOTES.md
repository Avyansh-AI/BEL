# BEL V1 (1.0.0-RC1) — Release Notes
**Release Date:** November 12, 2026  
**Product:** BEL — Behavioral Executive Logic  
**Platform:** Windows 10 / 11 (x64)  
**Default Reasoning Model:** `gemma4:e4b-it-qat` (Local Ollama)

---

## 1. Release Highlights

**BEL V1 (1.0.0-RC1)** unifies the complete 11-stage Behavioral Executive Logic architecture into a single local-first, security-hardened Windows executive assistant while preserving the official minimal animated orb interface (`frontend/`).

### What's New & Converged in BEL V1
1. **Stage 1 — Persistent Autonomous Execution Engine (`/api/autonomous/*`):**
   - Full `REQUEST → UNDERSTAND → PLAN → EXECUTE → OBSERVE → VERIFY → REPLAN → COMPLETE` lifecycle backed by SQLite checkpoints.
   - Parallel dependency-aware DAG execution, automatic replanning with fallback tools, restart checkpoint recovery (`recover_interrupted()`), evidence-gated completion, and human approval gates for consequential steps.
2. **Stage 2 — 10-Role Multi-Agent Intelligence & Sandboxed RSI (`/api/agents/*`):**
   - Coordinated `Manager`, `Research`, `Coding`, `Engineering`, `Analyst`, `Designer`, `Testing`, `Security`, `Creative`, and `Memory` agents with `AgentMessageBus`, isolated contexts, `SharedProjectState`, independent challenge/verification, token budgets, and bound domain services.
   - Sandboxed Recursive Self-Improvement (`rsi/`) with strict Axiom 1 protection of core kernel files.
3. **Stage 3 — Resilient Multi-Provider Model Routing:**
   - Local Ollama (`gemma4:e4b-it-qat`) discovery and SHA-256 verification, hardware RAM/VRAM safety gate (`SystemMonitor`), and opt-in adapters for Groq, Google Gemini, OpenRouter, Token Harbor, and ChatGPT with quota ledgers, rate-limit cooldowns, and automatic failover.
4. **Stage 4 — Hybrid RAG & SQLite Personal Memory (`/api/personal/memory/*`):**
   - SQLite FTS5 + vector hybrid retrieval alongside a persistent `PersonalMemoryManager` supporting importance scoring, contradiction detection/resolution, TTL retention policies, JSON export/restore, and proactive Morning/Evening Executive Briefings.
5. **Stage 5 — Offline Voice, Bilingual Profiles & Acoustic Intelligence (`/api/speech/*`, `/api/audio/*`):**
   - Offline Windows WinRT/SAPI TTS, refined British English (`en_bel`, Gemini Charon voice direction) and mature Indian Hindi (`hi_bel`) voice profiles, sentence-level streaming, barge-in interruption, 16 kHz PCM wake-word DSP (`AcousticWakeDetector`), acoustic scene classification, meeting action-item extraction, and opt-in local speaker ID with instant purge.
6. **Stage 6 — Closed-Loop Computer Use, Browser & Smart Devices (`/api/automation/workflows/*`, `/api/devices/*`):**
   - Win32 mouse/keyboard actuation with coordinate clamping and hotkey blacklists, UI Automation control grounding, visual pixel-diff verification, unexpected modal detection, path-hardened workflow recording/replay, Playwright Chromium automation, and HMAC-authenticated smart-device control.
7. **Stage 7 — Unified Multimodal Intelligence (`/api/multimodal/*`):**
   - Image/chart/wireframe inspection, PDF/Markdown/HTML document layout parsing, perceptual image comparison, video frame scene-change detection, consent-gated camera context, and grounded cross-modal reasoning.
8. **Stage 8 — SSRF-Safe Web Research & Fault-Isolated Integrations (`/api/research/query`, `/api/integrations/*`):**
   - Multi-source web research with SSRF metadata/private IP blocking (`is_safe_url()`), domain credibility scoring, cross-source contradiction detection, fact-vs-assumption separation, and a permission-gated `IntegrationHub` (Gmail, Google Calendar, GitHub, REST API, Webhook, Local Network) with per-call deadline timeouts.
9. **Stage 9 — BEL Code Software Engineering Agent (`/api/coding/bel_code/*`):**
   - AST code analysis, multi-language repository inspection, atomic edits with rollback, isolated `pytest` runner, Git branch/diff/commit automation, static security vulnerability scanning, path-hardened development sessions, end-to-end `deliver_feature()`, and `.zip` project packaging.
10. **Stage 10 — Creative Development Studio (`/api/creative/studio/*`):**
    - Blender 4.4 headless bridge, procedural glTF/OBJ generation, software rasterizer fallback, and automatic blank/dark render inspection & correction; Godot 4 project/scene/GDScript scaffolding, auto-repair, and `.zip` packaging; Unreal Engine 5 `.uproject`, C++ `AActor`, and Editor Python script generation.
11. **Stage 11 — Production Security & Reliability (`/api/security/*`, `/api/system/*`):**
    - Owner session + CSRF + Host validation, Windows DPAPI secret vault, `PermissionManager`, `NetworkEgressGuard`, SHA-256 hash-chained `TamperEvidentAuditLog`, `SignedUpdateVerifier`, `APIKeyRotationManager`, `CrashWatchdog`, and Zip-Slip-hardened AES-256-GCM SQLite backups.

---

## 2. Verification Summary

- **Python Backend Test Suite:** `856 passed, 0 failed` (`100%` pass rate)
- **Frontend Test Suite & Build:** `26 passed, 0 failed` (`frontend/dist` production bundle verified)
- **Golden Convergence Validator:** `CERTIFIED` ([BEL_V1_VALIDATION_MANIFEST.json](file:///c:/Users/Dell/Documents/Ai%20projects/BEL/BEL_V1_VALIDATION_MANIFEST.json))
- **Continuous Soak Harness:** `1,128` cycles (`18,048` checks, `0` failures, `0` crashes) over `3.41 hours`
