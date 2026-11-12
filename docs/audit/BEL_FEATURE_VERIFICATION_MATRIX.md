# BEL V1 — Feature Verification Matrix

| Feature | Module | Test ID | Result | Evidence | Remaining issue |
|---|---|---|---|---|---|
| Autonomous Execution Engine (DAG + Checkpoints + Verify) | `autonomous_engine.py` | `SOAK-A01` | **PASS** | DAG completed with 3 verified steps (`task_id=task-2d480e4ed2db`) | None |
| Restart Recovery & Checkpoint Continuity | `autonomous_engine.py` | `SOAK-A02` | **PASS** | Interrupted task resumed without losing completed step s1 (`recovered=1`) | None |
| Multi-Agent Orchestration & Challenge | `multi_agent.py` | `SOAK-A03` | **PASS** | 10-agent registry + parallel delegation + independent verification passed (`tokens=512`) | None |
| Local Ollama + Gemma 4 E4B Discovery & Memory Gate | `models.py` | `SOAK-B01` | **PARTIAL** | Ollama & Gemma 4 E4B discovered, but live inference blocked by low free RAM (1625 MB < 5500 MB) (`exe=C:\Users\Dell\AppData\Local\Programs\Ollama\ollama.EXE, models=D:\Ollama Models`) | Free host RAM >= 6 GiB for live Gemma 4 E4B load |
| Provider Outage & Fallback Routing | `routing.py` | `SOAK-B02` | **PASS** | Local outage automatically failed over to cloud provider (mocked transport) (`[{'provider': 'local', 'status': 'offline'}, {'provider': 'groq', 'status': 'ok'}]`) | Live cloud inference requires explicit owner opt-in |
| Personal Memory Audit, Contradiction & Export/Restore | `personal_ecosystem.py` | `SOAK-C01` | **PASS** | Contradiction resolution, export, and restart restore verified (`entries=1`) | None |
| Offline TTS + English/Hindi Voice Profiles | `speech_tts.py / personal_ecosystem.py` | `SOAK-D01` | **PASS** | Offline WinRT TTS synthesized 74766 bytes + Hindi profile chunked (`wav_bytes=74766`) | None |
| Wake-Word DSP & Offline ASR Status | `wake_detector.py / speech_engines.py` | `SOAK-D02` | **PARTIAL** | AcousticWakeDetector DSP verified; WhisperCpp weights not installed on host (`Install the pinned whisper.cpp runtime and model explicitly; no automatic download is performed.`) | Install pinned whisper.cpp weights for full offline ASR |
| ComputerUseOrchestrator (Approval, Recovery, Replay) | `computer_use.py` | `SOAK-F01` | **PASS** | Workflow replay, approval gate, clipboard & fallback recovery verified (`2/2 actions`) | None |
| BELCodeAgent (Inspect, Edit, Scan, Package) | `bel_code.py` | `SOAK-G01` | **PASS** | Repo inspection, edit, security scan, session persistence & packaging passed (`zip_bytes=278`) | None |
| CreativeStudio (Blender, Godot 4, UE5) | `creative_studio.py` | `SOAK-H01` | **PARTIAL** | Scaffolding, inspection & fallback rendering passed; live binaries missing: Blender, Godot4, UE5 (`render=C:\Users\Dell\Documents\Ai projects\BEL\sight\data\soak_12h_isolated\cycle_sandbox\creative\blender\cube_render_1794490062.png`) | Install Blender, Godot4, UE5 on host |
| UnifiedMultimodalReasoner & VideoAnalyzer | `multimodal_unified.py` | `SOAK-I01` | **PASS** | Image diff, video scene-change & grounded cross-modal reasoning passed (`evidence=3`) | None |
| Live FastAPI Server Health & Lifecycle | `api.py` | `SOAK-J01` | **PASS** | FastAPI create_app() /api/health returned 200 in 188.0ms (`latency_ms=188.0`) | None |
| NetworkEgressGuard & TamperEvidentAuditLog | `production_hardening.py` | `SOAK-K01` | **PASS** | SSRF egress block + SHA-256 hash-chained audit log verified (`chain_valid=True`) | None |
| Backup/Restore (.sqlite3) & CrashWatchdog Recovery | `backup_restore.py / crash_watchdog.py` | `SOAK-L01` | **PASS** | Encrypted .sqlite3 backup/restore + CrashWatchdog recovery verified (`restored=['sight.sqlite3']`) | None |
| WebResearchEngine & Fault-Isolated IntegrationHub | `web_intelligence.py` | `SOAK-W01` | **PASS** | Multi-source citation + fault-isolated connector failure verified (`1 source, 1 isolated failure`) | None |
