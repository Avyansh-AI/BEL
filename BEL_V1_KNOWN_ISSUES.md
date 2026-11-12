# BEL V1 — Known Issues & Host Environmental Constraints
**Date:** November 12, 2026  
**Codebase:** `c:/Users/Dell/Documents/Ai projects/BEL`

---

## 1. Software Defects Status

- **Open Critical / High / Medium Code Defects:** **0**
- All 854 Python backend tests and 26 frontend tests pass (`100%` pass rate).
- All 5 security/persistence defects identified during the V1 codebase audit were fixed and verified with dedicated regression tests in [test_bel_v1_validation_suite.py](file:///c:/Users/Dell/Documents/Ai%20projects/BEL/sight/tests/test_bel_v1_validation_suite.py).

---

## 2. Host Hardware & Environmental Constraints (Truthful Qualification Matrix)

In strict compliance with BEL V1 reporting rules, capabilities that depend on host memory availability or optional external binaries are reported transparently below:

| Capability / Integration | BEL Code & Fallback Status | Host Environment Observation | Qualification Status | Remediation / Operator Action |
|---|---|---|---|---|
| **Local `gemma4:e4b-it-qat` Live Weight Loading** | `OllamaProvider` discovers `ollama.exe` and verifies SHA-256 blobs in `D:\Ollama Models`; `SystemMonitor` memory safety gate prevents host freeze | Host had `~1.15–1.8 GiB` available RAM during testing; loading the `4.5 GiB` quantized model requires `>= 5.5 GiB` free RAM | **PARTIAL (RAM-Gated on Host)** | Close heavy host processes so available RAM exceeds `5.5 GiB`, or enable an approved cloud fallback policy in Settings. |
| **Blender 4.4 Headless 3D Engine** | `BlenderAgent` discovers `C:\Program Files\Blender Foundation\Blender 4.4\blender.exe`, generates glTF/OBJ, runs headless renders, and includes a pure-Python software rasterizer fallback | Blender 4.4 is installed on host and verified | **PASS** | None required. |
| **Godot 4 Engine Binary (`godot`)** | `GodotAgent` & `CreativeStudio` scaffold full `project.godot`, `.tscn` scenes, and `.gd` scripts, auto-repair missing `extends` headers, validate syntax, and package `.zip` bundles | `godot` executable is not installed on the current host `PATH` | **PARTIAL (Scaffolding & Validation PASS; Live Binary Not Installed)** | Install Godot 4.x and add `godot` to `PATH` (or set `GODOT_EXECUTABLE`) to enable live headless scene execution. |
| **Unreal Engine 5 Binary (`UnrealEditor-Cmd.exe`)** | `UnrealAgent` & `CreativeStudio` scaffold `.uproject`, C++ `AActor` headers, Editor Python scripts, and Web Remote Control payloads | Unreal Engine 5 is not installed on the current host | **PARTIAL (Scaffolding & Script Generation PASS; Live Engine Not Installed)** | Install Unreal Engine 5.4+ and enable the Web Remote Control & Python Editor Script plugins for live editor execution. |
| **Offline `whisper.cpp` ASR Binary & Weights** | `WhisperCpp` engine adapter, SHA-256 asset verifier, and automatic fallback to Windows `System.Speech` (`windows-speech`) are implemented and tested | Pinned `whisper-cli.exe` / `ggml-base.bin` weights are not provisioned in `%LOCALAPPDATA%\BEL\models\asr`; Windows `System.Speech` fallback is active | **PARTIAL (Windows Speech Active; Whisper Weights Optional)** | Run `sight/scripts/setup_whisper_cpp.ps1` to download and verify the pinned CPU `whisper.cpp` binary and model weights. |
| **12-Hour Continuous Soak Duration** | Resumable soak harness ([run_12h_soak.py](file:///c:/Users/Dell/Documents/Ai%20projects/BEL/sight/scripts/run_12h_soak.py)) completed **1,128 cycles** (`18,048` checks, **0 failures**) over `12,265.73 s` (`~3.41 hours`) | `30,934.27 s` (`~8.59 hours`) of wall-clock soak time remain to reach the full `43,200 s` (12.0h) mark | **IN PROGRESS / RESUMABLE (0 Failures)** | Resume at any time with `.\.venv\Scripts\python.exe scripts\run_12h_soak.py --duration-seconds 43200 --resume`. |
