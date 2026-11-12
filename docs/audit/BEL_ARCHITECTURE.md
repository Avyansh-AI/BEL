# BEL (Behavioral Executive Logic) — System Architecture

BEL is designed as a multimodal, autonomous-capable personal AI operating system inspired by MCU J.A.R.V.I.S., engineered with a strict **fail-closed, local-first, privacy-by-design** paradigm.

---

## 1. High-Level Architecture Diagram

```mermaid
flowchart TD
    subgraph CLIENT["Presentation Layer (React 18 + Vite)"]
        UI["Minimalist HUD Interface"]
        ORB["Audio-Reactive 3D Particle Wave Sphere"]
        PTT["Push-to-Talk 16kHz PCM Stream"]
        WS_CLIENT["Encrypted WebSocket Client (/ws/app)"]
    end

    subgraph DESKTOP_HOST["Desktop Shell (pywebview / winforms)"]
        TRAY["System Tray & Status Monitor"]
        NATIVE_BRIDGE["Native Presentation Bridge"]
    end

    subgraph BACKEND_GATEWAY["Local Fast Gateway (FastAPI / 127.0.0.1:8080)"]
        AUTH["Token Claim & CSRF Guard"]
        SECURITY["Credential Redaction & URL Normalizer"]
        SYSTEM_SENTRY["RAM / VRAM Hardware Sentry"]
    end

    subgraph EXECUTIVE_CORE["BEL Executive Core (`sight_core/bel.py`)"]
        JOURNAL["SQLite Preimage Undo Journal"]
        NEEDLE["Needle Router (Intent Matching)"]
        LOCK["Sequential Action Lock"]
        PRE_COMPRESS["Context Pre-Compression Checkpointer"]
    end

    subgraph LOCAL_INTELLIGENCE["Local & Hybrid Intelligence Engine"]
        OLLAMA["Local Ollama Daemon (Llama 3.2 1B / Gemma 2 2B)"]
        CLOUD_ROUTER["Model Router (Groq / OpenAI / Anthropic)"]
        WHISPER["Whisper C++ Local Dictation (ggml-tiny.bin)"]
        PIPER["Piper Local Offline TTS Engine"]
    end

    subgraph CAPABILITY_STORAGE["Storage & Tool Subsystems"]
        BRAIN_STORE["BrainStore (SQLite Memory & Preferences)"]
        WORKSPACE["Private Local Workspace (Exclusive Windows Handles)"]
        WIN_APPS["Windows App Broker (Process32 / EnumWindows)"]
        FORGE["Forge Skill Synthesis Sandbox (-I -S Subprocess)"]
    end

    CLIENT <--> |HTTP / WebSocket| BACKEND_GATEWAY
    DESKTOP_HOST <--> CLIENT
    BACKEND_GATEWAY --> SYSTEM_SENTRY
    BACKEND_GATEWAY --> EXECUTIVE_CORE
    EXECUTIVE_CORE --> LOCAL_INTELLIGENCE
    EXECUTIVE_CORE --> CAPABILITY_STORAGE
```

---

## 2. Architectural Pillars

### 2.1 The Executive Boundary (One Action, Exact Grant)
The AI model has **no direct execution handles**. Every tool proposal emitted by the model generates a cryptographic execution proposal specifying exact normalized parameters. The user must explicitly approve the proposal through the presentation layer. Upon approval, a single-use action ticket is granted and consumed immediately.

### 2.2 Win32 Preimage Journaling & Instant Undo
Before any file mutation (`files.create`, `files.edit`, `files.rename`) takes place on the host filesystem:
1. An exclusive Windows file lock is acquired (`kernel32.CreateFileW` with deny-write/delete flags).
2. The exact pre-image bytes and SHA256 checksum are written to `bel_undo` in SQLite under an active database transaction.
3. The mutation executes and validates post-state SHA256.
4. Any mismatch marks the transaction `unverified` and halts.
5. The user can invoke `files.undo` at any point to restore the exact pre-image bytes.

### 2.3 Hardware Telemetry Sentinel
Because local speech recognition and LLM inference can saturate host RAM on 16GB systems:
- Real-time polling of host RAM, CPU, and GPU VRAM via `psutil` and `pynvml`.
- Hard load-shedding floor: if free host RAM drops below 500 MiB or VRAM below 300 MiB, heavy operations are refused or diverted to cloud fallbacks.

### 2.4 Multimodal Voice Pipeline
- Capture: HTML5 Web Audio API at 16kHz mono PCM, bounded by a 20-second hard cap to prevent memory leaks.
- Recognition: Whisper C++ running quantized `ggml-tiny.bin` offline with Windows Dictation fallback.
- Visual Feedback: Real-time audio waveform drives dynamic vertex displacement on the 3D particle sphere orb.
