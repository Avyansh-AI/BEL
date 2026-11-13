# BEL V1.0 — Remaining Issues & Environmental Limitations Register

**Release Version:** `1.0.0-RC1`  
**Audit Date:** November 13, 2026

---

## 1. Critical / High / Medium Software Defects

- **Open Critical Defects:** `0`
- **Open High Defects:** `0`
- **Open Medium Defects:** `0`

All defects discovered during the V1 convergence and final polishing phases (including the `Start-BEL.ps1` hidden window flag, `rsi/engine.py` auto-heal `repaired_code` propagation, `ASTSecurityAuditor` import inspection, `backup_restore.py` Zip-Slip containment, `computer_use.py` workflow ID path traversal, `bel_code.py` workspace path containment, and `web_intelligence.py` SSRF private/loopback IP blocking) have been repaired and verified by automated regression tests.

---

## 2. Documented Environmental & Hardware Constraints

| ID | Subsystem | Constraint Description | Mitigation / Behaviour in BEL V1.0 | Severity |
| :--- | :--- | :--- | :--- | :--- |
| **LIM-01** | **Wake-Word Acoustic Model** | Continuous low-power neural wake-word spotting requires an owner-enrolled ONNX model file in `owner-data`. | `AcousticWakeDetector` provides deterministic RMS energy + zero-crossing-rate (ZCR) voice activity gating and cleanly reports `"wake model unavailable"` until enrolled, while push-to-talk dictation works out of the box. | Low (By Design) |
| **LIM-02** | **External DCC Binaries (Blender / Godot 4 / Unreal Engine 5)** | Live headless 3D/game rendering requires the respective third-party engine binary to be installed on the host machine. | `CreativeStudioOrchestrator` validates all generated scripts via AST safety checks and executes in dry-run simulation mode with full asset provenance when external DCC executables are not installed. | Low (Environmental) |
| **LIM-03** | **Physical Smart-Home / IoT Hardware** | Real LAN actuation requires physical smart devices on the local subnet. | `SmartDeviceBridge` enforces explicit discovery consent and HMAC-SHA256 command tokens, operating against verified device state adapters when physical hardware is absent. | Low (Environmental) |
| **LIM-04** | **Cloud Provider Quotas** | Free-tier cloud APIs (Groq, Gemini, OpenRouter) enforce external rate limits (HTTP 429). | `ModelRouter` tracks cooldowns per provider and automatically fails over to local Ollama (`gemma4:e4b-it-qat`) without crashing or losing conversation state. | Low (External API) |
