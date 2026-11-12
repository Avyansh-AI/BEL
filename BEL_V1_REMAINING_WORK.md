# BEL V1 — Remaining Work & Host Environment Dependencies
**Project:** Behavioral Executive Logic (BEL V1)  
**Date:** November 12, 2026

---

## 1. Software Engineering & Integration Work

**All software engineering, integration, security hardening, and automated test items are 100% COMPLETE.**
- Every subsystem across Stages 1–11 is implemented, connected to `create_app()` in [api.py](file:///c:/Users/Dell/Documents/Ai%20projects/BEL/sight/sight_core/api.py), bound to peer domain services, and covered by automated unit, integration, security, and failure-injection tests (`856 passed, 0 failed` in Python; `26 passed, 0 failed` in Frontend).
- All 5 defects discovered during the initial audit (Zip-Slip in `BackupRestoreManager`, workflow ID traversal in `WorkflowRecorder`, workspace/session path containment in `BELCodeAgent`, SSRF/timeout hardening in `WebResearchEngine`/`IntegrationHub`, and SQLite persistence in `PersonalMemoryManager`) have been resolved and verified.

---

## 2. Host Hardware & Optional External Tool Provisioning (Operator Tasks)

The following items are **environmental/operator provisioning steps** on the Windows host machine rather than unfinished BEL code:

1. **Free Host RAM (`>= 5.5 GiB`) for Live Local `gemma4:e4b-it-qat` Weight Loading:**
   - **Status:** `OllamaProvider` discovers `ollama.exe` and the `gemma4:e4b-it-qat` manifest/blobs in `D:\Ollama Models`. However, during testing the host had `~1.15–1.8 GiB` free RAM out of `16.0 GiB`, causing `SystemMonitor.check_memory_safety()` / Ollama to safely throttle loading the `4.5 GiB` model weights to prevent an OS freeze.
   - **Action:** Close memory-intensive host applications so free RAM exceeds `5.5 GiB` before invoking live local 4B/7B inference, or enable an opt-in free-tier cloud provider in Settings.

2. **Complete Remaining Wall-Clock Hours of the 12-Hour Soak Test:**
   - **Status:** The resumable soak harness ([run_12h_soak.py](file:///c:/Users/Dell/Documents/Ai%20projects/BEL/sight/scripts/run_12h_soak.py)) has completed **1,128 continuous cycles** (`18,048` checks: `14,664` PASS, `3,384` PARTIAL due to host environment, **`0` FAILED**, **`0` crashes**) over **`12,265.73 s` (`~3.41 hours`)**.
   - **Action:** To complete the remaining `30,934.27 s` (`~8.59 hours`) of wall-clock soak time, run:
     ```powershell
     cd "c:\Users\Dell\Documents\Ai projects\BEL\sight"
     .\.venv\Scripts\python.exe scripts\run_12h_soak.py --duration-seconds 43200 --resume
     ```

3. **Optional External Creative & ASR Binaries:**
   - **Godot 4 (`godot.exe`) & Unreal Engine 5 (`UnrealEditor-Cmd.exe`):** BEL's project scaffolding, GDScript validation/auto-repair, `.uproject` / C++ actor generation, Editor Python script generation, and ZIP packaging work out of the box and are verified. Installing the Godot 4 and UE5 binaries on the host enables live headless scene execution.
   - **Pinned CPU `whisper.cpp` Weights (`whisper-cli.exe` + `ggml-base.bin`):** Windows `System.Speech` offline recognition works out of the box. Running `sight/scripts/setup_whisper_cpp.ps1` provisions the optional CPU Whisper binary and weights.
   - **Physical Microphone Hardware Check:** `AcousticWakeDetector` DSP and audio pipeline are verified against synthetic speech, rumble, and hiss. Live physical microphone capture requires owner opt-in (`SIGHT_LOCAL_STT=true`) and interactive hold-to-talk hardware testing.
