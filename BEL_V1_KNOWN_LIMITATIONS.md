# BEL V1 — Known Limitations & Environmental Boundaries
**Date:** November 12, 2026  
**Version:** 1.0.0-RC1

---

## 1. Distinction Between Software Capabilities and Host/Hardware Limitations

In accordance with BEL V1 release standards, this document distinguishes clearly between:
- **Implemented & Verified Software Features:** All 11 stages of BEL V1 (`856` Python tests + `26` frontend tests passing).
- **Hardware-Dependent Features:** Capabilities requiring physical peripherals (microphone, camera, smart-home LAN devices) or `>= 5.5 GiB` of free host RAM.
- **Environment-Dependent Features:** Capabilities that integrate with optional third-party desktop engines (`Godot 4`, `Unreal Engine 5`, `whisper.cpp` CLI) when installed on the host.

---

## 2. Documented Limitations

1. **Local `gemma4:e4b-it-qat` Inference Memory Requirement (`>= 5.5 GiB` Free RAM):**
   - While `OllamaProvider` discovers `ollama.exe` and verifies the `gemma4:e4b-it-qat` weights in `D:\Ollama Models`, loading the `4.5 GiB` model into memory requires `>= 5.5 GiB` of available host RAM.
   - When available host RAM is low (observed at `~1.15–1.8 GiB` free on the 16 GiB development host), `SystemMonitor.check_memory_safety()` intentionally throttles local inference to prevent Windows paging stalls or system freezes.

2. **Optional External Game Engines (Godot 4 & Unreal Engine 5):**
   - **Blender 4.4** is installed on the host (`C:\Program Files\Blender Foundation\Blender 4.4\blender.exe`) and verified live.
   - **Godot 4 (`godot.exe`)** and **Unreal Engine 5 (`UnrealEditor-Cmd.exe`)** are not installed on the current host machine. BEL's project scaffolding, GDScript validation/auto-repair, `.uproject` / C++ `AActor` generation, Editor Python script generation, and `.zip` packaging are fully verified, while live headless execution of Godot/UE5 binaries requires installing those engines on the host.

3. **Offline Speech Recognition (`whisper.cpp` vs. Windows `System.Speech`) & Wake-Word Model:**
   - Offline speech recognition defaults to Windows `System.Speech` (`windows-speech`) unless the owner provisions the pinned CPU `whisper.cpp` binary and weights via `sight/scripts/setup_whisper_cpp.ps1`.
   - `AcousticWakeDetector` performs real-time 16 kHz PCM RMS energy, zero-crossing rate (ZCR), and syllable-burst VAD gating (verified against low-frequency rumble, high-frequency hiss, and short speech false activations), but does not include a custom neural keyword-spotting ONNX model trained specifically on the phoneme `"BEL"`.
   - Microphone capture is disabled by default and requires explicit owner opt-in (`SIGHT_LOCAL_STT=true`) and hold-to-talk review before sending.

4. **Cloud Providers & External Connectors Disabled by Default:**
   - By design, all external LLM providers (`groq`, `gemini`, `openrouter`, `tokenharbor`, `chatgpt`) and external `IntegrationHub` connectors (`gmail`, `google_calendar`, `github`, `rest_api`, `webhook`, `local_network`) start **disabled** and require explicit owner configuration, DPAPI vault credentials, and write-approval grants.

5. **12-Hour Continuous Soak Test Wall-Clock Completion:**
   - The resumable soak harness ([run_12h_soak.py](file:///c:/Users/Dell/Documents/Ai%20projects/BEL/sight/scripts/run_12h_soak.py)) has completed **1,128 cycles** (`18,048` checks, **`0` failures**, **`0` crashes**) over **`3.41 hours` (`12,265.73 s`)**. Completing the remaining `8.59 hours` of the 12-hour wall-clock target requires leaving `run_12h_soak.py --duration-seconds 43200 --resume` running uninterrupted on the host.
