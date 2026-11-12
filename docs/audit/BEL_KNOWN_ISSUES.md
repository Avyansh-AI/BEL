# BEL (Behavioral Executive Logic) — Known Issues & Technical Debt

This document tracks all identified technical debt, hardware constraints, blocked integrations, and known limitations in BEL.

---

## 1. Active Issues & Limitations

| Issue ID | Severity | Component | Description | Workaround / Planned Fix | Status |
| :--- | :---: | :--- | :--- | :--- | :---: |
| **ISSUE-003** | Medium | Local Model Service | Local Ollama daemon is not auto-managed; if the service is stopped, local model calls fail. | Implement auto-start of cached portable Ollama binary (`.cache/preview2/ollama-0.40.9`) on demand. | **Open** |
| **ISSUE-005** | Low | Folder Name | Workspace root directory is named `Sight` instead of `BEL` due to active file handles held by the IDE. | Documented clean 3-step manual rename process for the user. | **Documented** |
| **ISSUE-006** | Low | Starlette Test Warning | Pytest outputs deprecation warning: `Using httpx with starlette.testclient is deprecated; install httpx2 instead.` | Harmless deprecation warning from upstream Starlette; will update requirements.txt in Stage 6. | **Low Priority** |

---

## 2. Resolved Issues

| Issue ID | Date Resolved | Component | Description | Resolution |
| :--- | :---: | :--- | :--- | :--- |
| **FIX-001** | 2026-11-10 | Desktop Apps | `test_actual_win32_enumeration_is_read_only` failed because Win32 `EnumWindows` returned 0 with `GetLastError() == 0` on Windows 11. | Updated check in `sight_core/windows_apps.py` to verify `ctypes.get_last_error() != 0`. Verified with 20/20 tests passing. |
| **FIX-002** | 2026-11-10 | Repo Hygiene | Dangling worktree `BEL-local-dictation-preview` caused absolute path locking. | Pruned dangling worktree and merged `bel/offline-voice-preview2` cleanly into `main`. |
| **FIX-003** | 2026-11-10 | Hardware Sentry | Concurrent Whisper and local Ollama inference drops free host RAM to 67-91 MiB, risking system freeze. | Implemented native Win32 + NVML hardware monitor in `sight_core/system_monitor.py` and memory sentinel in `api.py` with 300 MiB floor. |
| **FIX-004** | 2026-11-10 | UI / Visuals | Frontend Orb was a 2D SVG ring instead of an MCU-inspired 3D particle sphere. | Upgraded `Orb.tsx` to 520-point 3D Fibonacci golden-spiral particle wave sphere with audio reactive ripples and radar sweep. |
| **FIX-005** | 2026-11-10 | Knowledge & RAG | FastAPI route collision: `/api/learning/memory/unified` collided with parameterized `{identifier}` route resulting in HTTP 404. | Placed static `/unified` route ahead of parameterized `{identifier}` route in `learning_api.py`. Verified with 16/16 RAG tests passing. |
| **FIX-006** | 2026-11-10 | RSI Harness | In `synthesizer.py`, embedding `json.dumps()` in Python test runner emitted `null` instead of `None`, causing `NameError`. | Switched to `repr()` format to produce valid Python literals. Verified with 10/10 RSI tests passing. |
| **FIX-007** | 2026-11-10 | Speech Synthesis | `/api/speech/synthesize` returned HTTP 503 ("Local TTS is not installed"). Speech output was non-functional. | Implemented `LocalTTS` (`sight_core/speech_tts.py`) using WinRT `Windows.Media.SpeechSynthesis` with zero cloud telemetry, memory streaming, voice enumeration (`/api/speech/voices`), and pitch/rate/volume controls. Fully verified with 29/29 speech tests passing. |
