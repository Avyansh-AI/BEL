# BEL (Behavioral Executive Logic) — Test Report
**Test Run Date:** November 10, 2026  
**Test Harness:** `pytest 9.0.3` (Python 3.12.5), Node.js native test runner (`node --experimental-strip-types --test`)  
**Overall Result:** **384 / 384 Passed (100% Pass Rate)**  

---

## 1. Test Suite Breakdown

### 1.1 Backend Python Suites (`sight/tests/`)
| Test File | Total | Passed | Failed | Duration | Scope |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `test_bel_identity.py` | 11 | 11 | 0 | 0.05s | Bounded turn history, identity constants, immutable assistant boundaries. |
| `test_bel_tools.py` | 27 | 27 | 0 | 5.06s | Win32 exclusive file locks, atomic rollback, SHA256 preimage verification, execution budget. |
| `test_system_monitor.py` | 8 | 8 | 0 | 0.19s | RAM/CPU/VRAM telemetry, memory safety thresholds, load shedding, `/api/system/telemetry`. |
| `test_bel_pre_compress.py` | 2 | 2 | 0 | 0.95s | Hermes-style pre-compression memory checkpointing at 80% watermark and long-term memory persistence. |
| `test_bel_desktop.py` | 18 | 18 | 0 | 0.22s | Desktop controller lifecycle, system tray integration, window dispatch deadlines. |
| `test_windows_apps.py` | 20 | 20 | 0 | 0.06s | Win32 process enumeration, safe launcher allowlist, read-only window detection. |
| `test_needle.py` | 45 | 45 | 0 | 0.65s | Local small-model intent matching, parameter normalization, regex heuristics. |
| `test_learning.py` | 25 | 25 | 0 | 9.18s | BrainStore SQLite memory, Forge skill generation, sandboxed subprocess workers. |
| `test_speech_engines.py` | 37 | 37 | 0 | 1.85s | Whisper C++ binary detection, WAV 16kHz mono validation, engine fallback logic. |
| `test_speech_api.py` | 19 | 19 | 0 | 1.13s | WebSocket audio stream handling, 20s audio cap, session cancellation. |
| `test_capabilities.py` | 42 | 42 | 0 | 1.40s | Document generation, artifact hashing, sandbox isolation. |
| `test_core.py` | 56 | 56 | 0 | 18.20s | Session claim, CSRF token validation, request routing, rate limiting. |
| `test_routing.py` | 27 | 27 | 0 | 6.80s | Provider quotas, daily USD spend ceilings, model fallback chains. |
| `test_memory_integrity.py` | 14 | 14 | 0 | 2.15s | SQLite transaction atomicity, corruption detection, hash verification. |
| `test_audit_memory_transactions.py` | 5 | 5 | 0 | 1.56s | Event journaling, tamper resistance, audit log extraction. |
| **Backend Total** | **356** | **356** | **0** | **~50s** | |

### 1.2 Frontend Client Suites (`frontend/tests/`)
| Test File | Total | Passed | Failed | Duration | Scope |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `dictation.test.mjs` | 4 | 4 | 0 | 6ms | Audio capture cancellation, language option validation, session preservation. |
| `native.test.mjs` | 1 | 1 | 0 | 1ms | Native bridge initialization, crash prevention in web-only mode. |
| `transport.test.mjs` | 8 | 8 | 0 | 32ms | WebSocket ticket handshake, wire protocol parsing, action execution grants. |
| `voice.test.mjs` | 13 | 13 | 0 | 143ms | Push-to-talk microphone management, 20s audio cap, buffer cleanups. |
| **Frontend Total** | **26** | **26** | **0** | **201ms** | |

### 1.3 Client Production Build
- `tsc -b && vite build`: **0 errors, built in 4.48s** (Output: `dist/index.html`, `dist/assets/*`).

---

## 2. Regression Testing Policy

Every subsequent feature commit must pass:
1. All feature-specific tests.
2. The core regression suite (`test_bel_identity.py`, `test_bel_tools.py`, `test_system_monitor.py`, `test_bel_pre_compress.py`, `test_windows_apps.py`).
3. `npm test` inside `frontend`.
4. `npm run build` inside `frontend` (zero TypeScript or Vite bundling errors).
