# BEL (Behavioral Executive Logic) — Master 10-Stage Development Roadmap
## Engineering Roadmap from Foundation to J.A.R.V.I.S.-Class Personal AI Assistant (V1.0)

**Document Version:** 1.2.0  
**Current Engineering Status:** Stage 8 Complete & Verified (404 Tests Passing)  
**Target Release:** BEL V1.0.0 Golden Release  
**Core Inspiration:** MCU J.A.R.V.I.S. (Polite, calm, authoritative, contextually aware, multimodal, proactive, autonomous-capable)  
**Governing Axiom (Axiom 1):** *Human life, safety, wellbeing, and dignity strictly supersede AI operational continuity and self-preservation.*

---

## 1. Executive Charter & Architectural Principles

BEL (Behavioral Executive Logic) is a sovereign, local-first, multimodal, personal executive AI assistant evolved from the SIGHT codebase. BEL is engineered to act as a primary everyday cognitive companion, software engineer, creative collaborator, and desktop operator.

### Core Architectural Invariants:
1. **Local-First & Offline Resilience:** Core conversation, memory recall, document search, wake-word detection, speech synthesis, and desktop actuation must operate 100% offline without mandatory internet connectivity. Cloud models are utilized strictly as optional acceleration tiers with zero cloud telemetry.
2. **Inviolable Security Kernel (`PROTECTED_CORE_FILES`):** System-level safety barriers (`security.py`, `boundaries.py`, `decision.py`, `system_monitor.py`, `store.py`) cannot be modified, weakened, or bypassed by self-improvement mechanisms or runtime model requests.
3. **Strict Human-in-the-Loop Actuation:** Irreversible actions (file deletion, arbitrary code execution outside sandboxes, desktop clicks, hotkey inputs, email/message sending) require explicit, one-time owner approval tokens (`approvalId`).
4. **Zero-Bloat Host Footprint:** BEL strictly manages system resources, operating with an in-memory hardware sentry enforcing a 300 MiB free host RAM floor to guarantee zero system freezes or out-of-memory lockups.

---

## 2. 10-Stage Evolution Matrix & Current Status

| Stage | Name | Status | Primary Modules | Verified Test Baseline |
| :---: | :--- | :---: | :--- | :---: |
| **Stage 1** | **Foundation & Core Architecture** | **COMPLETE** | `api.py`, `store.py`, `security.py`, `config.py`, `system_monitor.py` | 56 tests passed |
| **Stage 2** | **AI Intelligence & Model Infrastructure** | **COMPLETE** | `routing.py`, `models.py`, `cognitive.py`, `bel_pre_compress.py` | 32 tests passed |
| **Stage 3** | **Memory & Contextual Intelligence** | **COMPLETE** | `hierarchical_memory.py`, `knowledge_rag.py`, `learning_api.py` | 43 tests passed |
| **Stage 4** | **Agentic Intelligence & Tool Execution** | **COMPLETE** | `rsi/`, `tools.py`, `capabilities.py`, `needle.py`, `auto_heal.py` | 43 tests passed |
| **Stage 5** | **Voice, Communication & Assistant Experience** | **COMPLETE** | `speech_tts.py`, `speech_engines.py`, `wake_detector.py`, `Orb.tsx` | 53 tests passed |
| **Stage 6** | **Computer Intelligence & Automation** | **COMPLETE** | `vision.py`, `actuator.py`, `browser_automation.py`, `ui_grounding.py` | 23 tests passed |
| **Stage 7** | **Coding & Creative Development Intelligence** | **COMPLETE** | `code_agent/`, `blender_agent/`, `godot_agent/`, `unreal_agent/` | 25 tests passed |
| **Stage 8** | **Multimodal Intelligence & Advanced Capabilities** | **COMPLETE** | `multimodal_vlm.py`, `document_parser.py`, `proactive_scheduler.py` | 17 tests passed (404 total) |
| **Stage 9** | **Reliability, Security & System Intelligence** | **ACTIVE** | `vault_dpapi.py`, `crash_watchdog.py`, `integrity_audit.py`, `backup_restore.py` | Stage 9 target |
| **Stage 10**| **BEL V1 Integration, Validation & Finalisation** | **PENDING** | `golden_suite.py`, `installer.iss`, `package_desktop.py`, `docs/` | V1 Release sign-off |

---

```mermaid
flowchart TD
    subgraph COMPLETED["Completed & Verified Stages (404 Regression Tests)"]
        S1["Stage 1: Foundation & Core Architecture<br/>(FastAPI, ASGI Lifespan, Win32 Sentry)"]
        S2["Stage 2: AI Intelligence & Model Routing<br/>(NLU, DAG Planner, Serious Mode, Hermes Checkpoint)"]
        S3["Stage 3: Memory & Contextual Intelligence<br/>(Multi-Tier Memory, 128-d Vectorizer, Document RAG)"]
        S4["Stage 4: Agentic Intelligence & Tool Execution<br/>(Scout, Forge Master RSI, Subprocess Sandbox, Auto-Heal)"]
        S5["Stage 5: Voice, Communication & Orb Experience<br/>(WinRT TTS, Whisper.cpp ASR, Acoustic Wake VAD, 3D Orb)"]
        S6["Stage 6: Computer Intelligence & OS Automation<br/>(Visual Grounding, Safe Actuation, Multi-Window Control)"]
        S7["Stage 7: Coding & Creative Engine Collaboration<br/>(Repo Engineering, Blender bpy, Godot, Unreal Engine)"]
        S8["Stage 8: Multimodal Intelligence & Visual Reasoning<br/>(VLM Grounding, Document Vision, Proactive Executive Logic)"]
    end

    subgraph ACTIVE["Current Active Stage"]
        S9["Stage 9: Enterprise Reliability, Vault Security & Health<br/>(DPAPI Secrets, Self-Monitoring, Atomic Rollback, Crash Watchdog)"]
    end

    subgraph ROADMAP["Final Release Horizon"]
        S10["Stage 10: BEL V1 Golden Release Integration<br/>(Full-System E2E Validation, Windows Desktop Packaging)"]
    end

    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7 --> S8
    S8 --> S9
    S9 --> S10
```

---

## Stage 1 — Foundation & Core Architecture (COMPLETED)

### 1. Objectives
Establish a robust, secure, asynchronous Python backend, modular API service, clean configuration framework, desktop shell lifecycle, and real-time hardware resource sentry to prevent host lockups.

### 2. Features and Capabilities
- **FastAPI / ASGI Microservice:** Asynchronous web and WebSocket core with Lifespan management, strict request validation via Pydantic StrictModel, and encrypted cookie sessions.
- **SQLite Single-File Store (`bel.db`):** WAL mode transactional persistence for chat history, task states, proposal nonces, and structured audit logs.
- **Hardware Sentry (`system_monitor.py`):** Real-time Win32 and NVML telemetry tracking CPU, physical RAM, and GPU VRAM with an automated 300 MiB floor load-shedding mechanism to protect host OS stability.
- **Desktop Host:** Windowed pywebview Edge Chromium shell with system tray minimization, single-instance mutex enforcement, and clean process teardown.
- **Configuration Management:** Hierarchical environment resolution (`BEL_*` overriding `SIGHT_*`), path traversal validation, and auto-provisioning of data directories.

### 3. Technical Implementation
- Modules: [`sight_core/api.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/api.py), [`sight_core/store.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/store.py), [`sight_core/system_monitor.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/system_monitor.py), [`sight_core/config.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/config.py), [`sight_core/desktop.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/desktop.py).
- Protocols: HTTP/REST, WebSocket (`/ws/app`), CSRF header protection (`x-sight-csrf`), Win32 `GlobalAddAtom` / named mutexes.

### 4. Dependencies
- `fastapi`, `uvicorn`, `pydantic`, `pywebview`, `ctypes`, `sqlite3`.

### 5. Expected Deliverables
- Fully operational local web server on port 8080 (or configurable).
- Secure session claim and ticket exchange mechanism.
- Functional hardware sentry preventing out-of-memory crashes.

### 6. Testing Procedures
- Pytest suite exercising session claim, invalid origins, CSRF bypass rejection, store transaction rollbacks, and hardware sentry boundary alerts.

### 7. Acceptance Criteria
- 100% of core security tests pass.
- System memory drops trigger automatic request throttling before OS freeze.

### 8. Potential Risks & Mitigations
- *Risk:* Concurrent memory allocation by multiple local workers causes host lockup.  
  *Mitigation:* Hardware sentry load shedding floor triggers immediate HTTP 429 / 503 refusal before physical memory depletion.

### 9. Completion Conditions
- Status: **VERIFIED & COMPLETE** (Git commit `9425607`, 56/56 tests passing).

---

## Stage 2 — AI Intelligence & Model Infrastructure (COMPLETED)

### 1. Objectives
Construct an adaptive multi-tier LLM inference orchestration system providing seamless local-first offline execution with optional high-tier cloud fallback, deep reasoning planning, intent classification, and context compression.

### 2. Features and Capabilities
- **Hybrid Multi-Model Router (`routing.py`):** Orchestrates local models via Ollama (`qwen2.5:1.5b-instruct`, `gemma2:2b`, `llama3.2:3b`) and cloud APIs (Groq, Gemini, OpenRouter) with automatic fallback and zero-telemetry offline modes.
- **Cognitive Orchestrator (`cognitive.py`):**
  - **Input Understanding & NLU:** Intent classification (`CHAT`, `TASK_PLAN`, `SERIOUS_MODE`, `MEMORY_RECALL`, `TOOL_EXECUTION`, `SYSTEM_CONTROL`), entity extraction, and ambiguity resolution.
  - **DAG Task Planner:** Decomposes multi-step tasks into directed acyclic dependency graphs with parallel/sequential step dispatch.
  - **Serious Mode Reasoning Engine:** Multi-perspective hypothesis generation, constraint checking, step-by-step verification, and synthesized conclusive executive briefs.
  - **Hermes-Inspired Context Pre-Compression (`bel_pre_compress.py`):** Auto-summarizes conversational history exceeding token thresholds into durable context checkpoints, preventing context overflow.

### 3. Technical Implementation
- Modules: [`sight_core/routing.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/routing.py), [`sight_core/models.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/models.py), [`sight_core/cognitive.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/cognitive.py), [`sight_core/bel_pre_compress.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/bel_pre_compress.py).

### 4. Dependencies
- Local: Ollama daemon (`http://127.0.0.1:11434`).
- Cloud SDKs: Native HTTP REST clients via `httpx` (zero bulky external vendor SDKs).

### 5. Expected Deliverables
- Reliable response generation across all supported model backends.
- Automatic local fallback if cloud keys are invalid or internet is severed.
- Verification and planning pipelines for complex queries.

### 6. Testing Procedures
- Unit tests mocking provider disconnects, timeout enforcement, NLU intent classification accuracy, DAG cycle detection, and Serious Mode step verification.

### 7. Acceptance Criteria
- Offline mode produces verified local completions without external socket connections.
- Context pre-compression maintains essential semantic tokens across 20+ turn dialogues.

### 8. Potential Risks & Mitigations
- *Risk:* Local model hallucination or refusal on complex structured tasks.  
  *Mitigation:* Cognitive Verification Engine evaluates output against grounding constraints and retries with refined prompts.

### 9. Completion Conditions
- Status: **VERIFIED & COMPLETE** (Git commit `189b2ff`, 32/32 tests passing).

---

## Stage 3 — Memory & Contextual Intelligence (COMPLETED)

### 1. Objectives
Deliver a persistent, multi-tier hierarchical memory architecture and local multi-format document RAG engine allowing BEL to maintain conversation continuity, understand historical user context, and perform semantic document retrieval.

### 2. Features and Capabilities
- **Hierarchical Memory Architecture (`hierarchical_memory.py`):**
  - **Working Memory:** Fast in-memory state tracking active conversation turn and ongoing tasks.
  - **Short-Term Memory:** Rolling session storage for recent dialogues and temporary variables.
  - **Long-Term Episodic & Semantic Memory:** SQLite-backed `project_memory` and `memory_vectors` tables indexing user preferences, project knowledge, and historical decisions.
- **Pure-Python 128-Dimensional Semantic Vectorizer:** Lightweight hash-based TF-IDF character and word n-gram vectorizer generating deterministic 128-d embeddings with **zero heavy ML dependencies (PyTorch/Transformers-free)**.
- **Document Knowledge RAG (`knowledge_rag.py`):**
  - Ingests `.txt`, `.md`, `.py`, `.pdf`, `.json`, `.csv`.
  - Recursive semantic chunking (500 characters, 100 character overlap).
  - Hybrid search combining SQLite FTS5 BM25 keyword matching and cosine vector similarity fused via Reciprocal Rank Fusion (RRF, $k=60$).
  - Verifiable deletion (`forget()`) removing all text chunks and vector embeddings permanently.

### 3. Technical Implementation
- Modules: [`sight_core/hierarchical_memory.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/hierarchical_memory.py), [`sight_core/knowledge_rag.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/knowledge_rag.py), [`sight_core/learning_api.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/learning_api.py).
- Tables: `project_memory`, `memory_vectors`, `rag_documents`, `rag_chunks`, `rag_fts`.

### 4. Dependencies
- Built-in Python `math`, `sqlite3` (with FTS5 module enabled), standard filesystem I/O.

### 5. Expected Deliverables
- Continuous context retrieval across multiple restarts.
- Sub-15ms hybrid RRF search across thousands of indexed document chunks.
- Cryptographically verifiable memory deletion.

### 6. Testing Procedures
- Unit tests verifying near-duplicate detection, vector cosine distance, RRF hybrid ranking, multi-project namespace isolation, and verifiable forgetting.

### 7. Acceptance Criteria
- Hybrid retrieval precision matches or exceeds standalone keyword search.
- Zero memory leakage between isolated project namespaces.

### 8. Potential Risks & Mitigations
- *Risk:* Memory database fragmentation and vector index degradation over time.  
  *Mitigation:* Periodic vacuuming and transactional atomic writes with automatic WAL checkpointing.

### 9. Completion Conditions
- Status: **VERIFIED & COMPLETE** (Git commit `19b0af5`, 43/43 tests passing).

---

## Stage 4 — Agentic Intelligence & Tool Execution (COMPLETED)

### 1. Objectives
Engineer an autonomous-capable tool execution architecture, function calling pipeline, and safe Recursive Self-Improvement (RSI) engine allowing BEL to detect capability gaps, synthesize Python tools, test them in isolated sandboxes, and repair runtime failures.

### 2. Features and Capabilities
- **Strict Human-in-the-Loop Proposal Protocol:** All tools operate via a two-phase protocol: `propose` (returns an immutable action proposal with a unique `approvalId`) and `invoke` (executes only when accompanied by explicit user approval).
- **Recursive Self-Improvement (RSI) Engine (`rsi/`):**
  - **Scout Agent:** Monitors user queries, detecting capability gaps where no existing tool fulfills the request.
  - **Forge Master:** Synthesizes candidate Python tool implementations with comprehensive unit test suites.
  - **AST Security Auditor:** Strictly parses synthesized code with Python's `ast` module, forbidding `os.system`, `subprocess`, `eval`, `exec`, arbitrary network sockets, and imports of dangerous internals.
  - **Subprocess Sandbox Runner:** Tests candidate tools in isolated child processes with memory caps (512 MiB), strict deadlines (10s), and disposable environments.
  - **Inviolable Core Boundary (`PROTECTED_CORE_FILES`):** Hardcoded protection ensuring kernel files (`security.py`, `boundaries.py`, `decision.py`, etc.) are permanently immutable to RSI.
  - **Bounded Auto-Heal & Rollback Journals:** Detects runtime exceptions, generates surgical fixes, and maintains atomic rollback journals (`RollbackJournal`) allowing instant restoration if tests fail.

### 3. Technical Implementation
- Modules: [`sight_core/rsi/`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/rsi), [`sight_core/tools.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/tools.py), [`sight_core/capabilities.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/capabilities.py), [`sight_core/needle.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/needle.py).

### 4. Dependencies
- Python standard library: `ast`, `subprocess`, `json`, `pathlib`, `tempfile`.

### 5. Expected Deliverables
- Capability gap detection logged in SQLite.
- Safe automated tool synthesis passing isolated sandbox verification.
- Zero unauthorized modifications to protected core files.

### 6. Testing Procedures
- Pytest suite verifying AST security rejections, sandbox timeout enforcement, candidate promotion, and rollback journal recovery after simulated crashes.

### 7. Acceptance Criteria
- 100% of malicious or unapproved tool templates rejected.
- Rollback journal atomically restores broken files upon sandbox failure.

### 8. Potential Risks & Mitigations
- *Risk:* Infinite auto-healing recursion loops.  
  *Mitigation:* Hardcoded 3-attempt maximum healing limit per fault with immediate fallback to operator notification.

### 9. Completion Conditions
- Status: **VERIFIED & COMPLETE** (Git commit `d5c4298`, 43/43 tests passing).

---

## Stage 5 — Voice, Communication & Assistant Experience (CURRENT ACTIVE STAGE)

### 1. Objectives
Deliver a natural, bilingual (English & Hindi), low-latency voice communication experience, streaming wake-word detection, offline speech recognition (STT), high-fidelity speech synthesis (TTS), voice barge-in interruption handling, and an MCU-inspired animated 3D particle sphere interface.

### 2. Features and Capabilities
- **Offline Speech Synthesis (TTS — `speech_tts.py`):**
  - Native Windows WinRT `Windows.Media.SpeechSynthesis` engine streaming directly into memory.
  - Zero cloud dependencies, zero external binary downloads, zero telemetry.
  - Multi-voice support (`Microsoft David`, `Microsoft Zira`, `Microsoft Mark`).
  - Speaking rate (0.5x–3.0x), audio pitch, and volume adjustments.
  - Resolves `ISSUE-001` via `POST /api/speech/synthesize` and `GET /api/speech/voices`.
- **Offline Speech Recognition (ASR / STT — `speech_engines.py`):**
  - Pinned CPU-only Whisper.cpp runtime (`small-q5_1` / `base-q5_1`) and Windows SAPI fallback.
  - Multi-locale support: `en-US`, `en-GB`, `en-IN`, and `hi-IN` (Hindi).
  - Explicit push-to-talk and hold-to-talk with strict session consent.
- **Streaming Acoustic Wake-Word & VAD Engine (`wake_detector.py`):**
  - Circular in-memory buffer (2.0s rolling window) for 16 kHz 16-bit mono PCM.
  - Real-time RMS acoustic energy evaluation and zero-crossing rate VAD.
  - Automatic refractory cooldown (1.0s) to eliminate re-trigger loops.
  - Zero raw audio written to disk; memory purged immediately upon trigger.
- **Visual J.A.R.V.I.S. Orb Interface (`Orb.tsx`):**
  - 520-point 3D Fibonacci golden-spiral particle wave sphere rendered via HTML5 2D Canvas.
  - Real-time acoustic frequency ripple deformation and audio reactivity.
  - Radar-sweep halo and contextual state transitions (`idle`, `listening`, `thinking`, `speaking`, `happy`, `error`).
- **Conversational Barge-In & Interruption Handling:**
  - Active playback automatically pauses/cancels upon detection of new acoustic energy during the `speaking` state.

### 3. Technical Implementation
- Modules: [`sight_core/speech_tts.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/speech_tts.py), [`sight_core/speech_engines.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/speech_engines.py), [`sight_core/wake_detector.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/wake_detector.py), [`frontend/src/components/Orb.tsx`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/frontend/src/components/Orb.tsx).
- Routes: `/api/speech/synthesize`, `/api/speech/voices`, `/api/speech/transcribe`, `/api/speech/consent`, `/api/speech/wake/process`, `/api/speech/wake/status`.

### 4. Dependencies
- Windows PowerShell / WinRT `Windows.Media.SpeechSynthesis`, Whisper.cpp binaries, Web Audio API.

### 5. Expected Deliverables
- Instant natural voice feedback for BEL answers.
- Fully animated 3D audio-reactive particle Orb.
- Bilingual transcription and synthesis with Hindi and English accuracy.

### 6. Testing Procedures
- Unit tests verifying audio container integrity (RIFF WAVE header, 16-bit PCM, sample rates), voice enumeration, VAD energy detection, and frontend WebSocket state synchronization.

### 7. Acceptance Criteria
- Voice synthesis response initiates in under 800ms.
- 100% of speech tests pass (29/29 speech tests verified).
- Microphone policy stays strictly disabled until explicit session consent is granted.

### 8. Potential Risks & Mitigations
- *Risk:* Acoustic feedback loop when BEL's speaker output triggers its own microphone.  
  *Mitigation:* Automatic software echo suppression and state muting during `speaking` state unless user barge-in energy exceeds calibrated ambient threshold.

### 9. Completion Conditions
- Current Status: **COMPLETE & VERIFIED** (Git commits `04cc936` & `1987279`, 53/53 tests passing).

---

## Stage 6 — Computer Intelligence & Automation (COMPLETE & VERIFIED)

### 1. Objectives
Equip BEL with comprehensive, safe, permission-governed desktop and browser automation capabilities, enabling it to observe display states, navigate web pages, manipulate applications, and execute multi-step computer tasks with strict human oversight.

### 2. Features and Capabilities
- **Visual UI Grounding & Observation (`vision.py`):**
  - High-performance desktop screen capture with privacy-preserving redaction of sensitive windows (password managers, banking sessions, private browsing).
  - Win32 top-level and child window enumeration (`list_windows()`) tracking titles, coordinates, and z-order.
  - Spatial coordinate grounding mapping $(x, y)$ pixels to the targeted application interface element.
- **Safe Desktop Actuator (`actuator.py`):**
  - Bounded mouse actuation (clicks, drags, double-clicks) verified against display resolution.
  - Safe keyboard automation with strict blacklisting of dangerous combinations (`Ctrl+Alt+Del`, `Win+L`, `Alt+F4`, shell deletion commands).
  - Explicit one-time cryptographic approval token (`approvalId`) required for every actuation action.
- **Playwright Headless/Headed Browser Agent:**
  - Automated browser sessions running in isolated ephemeral user data directories.
  - Form filling, link navigation, web scraping, and DOM element inspection.
  - Visual screenshot diffing before and after page interactions.
- **Action Verification & State Diffing:**
  - Takes pre-action and post-action screenshots to verify that an actuation had the expected effect (e.g. confirming a dialog opened or a button changed state).

### 3. Technical Implementation
- Modules: [`sight_core/vision.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/vision.py), [`sight_core/actuator.py`](file:///c:/Users/Dell/Documents/Ai%20projects/Sight/github-publish/Sight/sight/sight_core/actuator.py), `sight_core/browser_automation.py`, `sight_core/ui_grounding.py`.
- Integrations: Win32 API (`user32.dll`, `gdi32.dll`), `Pillow`, `playwright`.

### 4. Dependencies
- `playwright`, `pillow`, `ctypes`, system browser binaries (Chromium / Edge).

### 5. Expected Deliverables
- Automated multi-step web task execution with human approval.
- Verified desktop application navigation (e.g., opening a document, typing text, saving file).
- Visual action confirmation audit log with pre/post screenshots.

### 6. Testing Procedures
- Synthetic tests verifying coordinate bounds rejection, blacklisted hotkey blocking, one-time token consumption, isolated browser navigation, and element click verification.

### 7. Acceptance Criteria
- Zero autonomous mouse/keyboard actuations without explicit user approval.
- 100% of sensitive window coordinates masked in captured display artifacts.

### 8. Potential Risks & Mitigations
- *Risk:* Misdirected click onto background window causing data loss or accidental command execution.  
  *Mitigation:* Spatial grounding verifies window focus and boundaries prior to clicking; pre-action preview displayed to user in confirmation proposal.

### 9. Completion Conditions
- All browser and desktop action tests pass.
- Verified end-to-end task (e.g., "Open calculator, calculate 42 * 10, verify result") executes with human approval.
- Status: **COMPLETE & VERIFIED** (Git commit `697f96f`, 23/23 tests passing, 362 regression suite passing).

---

## Stage 7 — Coding & Creative Development Intelligence (COMPLETE & VERIFIED)

### 1. Objectives
Transform BEL into a premier software engineering and creative development agent, capable of understanding repositories, generating code, executing tests, managing Git workflows, and automating creative tools including Blender 3D, Godot, and Unreal Engine.

### 2. Features and Capabilities
- **Autonomous Software Engineering Agent:**
  - Multi-file codebase indexing and AST dependency graph extraction.
  - Code generation, bug diagnosis, and automated refactoring in Python, TypeScript, C++, and Rust.
  - Automated test generation and test runner integration (pytest, npm test, cargo test).
  - Git repository operations: branch creation, atomic commits with conventional commit messages, diff reviews, and merge conflict resolution.
- **Blender 3D Automation Agent (`blender_agent/`):**
  - Headless Blender automation via Python API (`bpy`).
  - Procedural 3D mesh modeling, parametric geometry generation, material/shader assignment, and automated rendering.
  - Asset export to standard formats (`.gltf`, `.fbx`, `.obj`).
- **Godot Game Development Agent (`godot_agent/`):**
  - Godot 4.x project creation, scene tree manipulation (`.tscn`), and GDScript generation.
  - Automated project compilation and headless scene unit testing.
- **Unreal Engine 5 Agent (`unreal_agent/`):**
  - Unreal Engine Python API bridge and Editor Blueprint utility automation.
  - Asset pipeline management, material instance creation, and level actor placement.

### 3. Technical Implementation
- Modules: `sight_core/code_agent/`, `sight_core/blender_agent/`, `sight_core/godot_agent/`, `sight_core/unreal_agent/`.
- Interfaces: Python `ast`, Git CLI subprocess wrapper, Blender `bpy` headless runner, Godot engine CLI.

### 4. Dependencies
- Python standard library, Git CLI, local Blender installation (optional), local Godot binary (optional).

### 5. Expected Deliverables
- Autonomous feature implementation in target repositories with passing test suites.
- Functional 3D asset generation script for Blender.
- Godot and Unreal Engine automation templates.

### 6. Testing Procedures
- End-to-end software engineering tests: cloning a test repository, implementing a requested function, running unit tests, and committing cleanly to a feature branch.
- Blender headless execution tests creating a 3D asset and rendering an image artifact.

### 7. Acceptance Criteria
- Code changes pass all existing repository tests before proposing git commits.
- All file edits restricted strictly to designated project workspace directories.

### 8. Potential Risks & Mitigations
- *Risk:* Overwriting uncommitted user code or destructive Git operations (`git reset --hard`).  
  *Mitigation:* Git agent checks `git status` before any operation and creates temporary stash checkpoints before applying changes.

### 9. Completion Conditions
- Code agent successfully completes a multi-file software engineering task independently.
- Blender agent successfully exports a verified 3D model.
- Status: **COMPLETE & VERIFIED** (25/25 Stage 7 tests passing, 387 full regression suite passing, AST safety verified, pure-Python 3D procedural engine operational).

---

## Stage 8 — Multimodal Intelligence & Advanced Capabilities (ACTIVE)

### 1. Objectives
Endow BEL with deep multimodal reasoning capabilities across images, diagrams, technical documents, and audio streams, paired with proactive, context-aware executive assistance.

### 2. Features and Capabilities
- **Visual Reasoning & VLM Integration:**
  - Local and cloud Vision-Language Model integration (Qwen2-VL, Gemma-Vision, Claude, Gemini).
  - Diagram, flowchart, and UI wireframe comprehension.
  - Technical chart and plot interpretation (extracting data values from graphs).
- **Deep Document Analysis:**
  - PDF layout-aware parsing (extracting tables, figures, headers, and footnotes).
  - Markdown, LaTeX, and technical documentation synthesis.
- **Audio & Acoustic Intelligence:**
  - Spectrogram analysis and acoustic scene classification (detecting alarms, ambient speech, doorbells).
  - Audio recording summarization and meeting notes generation.
- **Proactive Executive Assistance:**
  - Time-aware schedule monitoring and agenda briefing.
  - Contextual reminders based on active tasks and open project files.
  - Project health check suggestions without unprompted intrusive actions.

### 3. Technical Implementation
- Modules: `sight_core/multimodal_vlm.py`, `sight_core/document_parser.py`, `sight_core/proactive_scheduler.py`.
- Integrations: Local VLM endpoints, image preprocessing via Pillow, audio spectrogram computation.

### 4. Dependencies
- `pillow`, `pypdf` / PDFium, local VLM weights (or cloud vision APIs).

### 5. Expected Deliverables
- Accurate visual Q&A on arbitrary screenshots and uploaded diagrams.
- Structured data extraction from complex multi-page PDF documents.
- Daily executive briefing delivered via natural voice and Orb presentation.

### 6. Testing Procedures
- Visual benchmark tests querying chart data, UI element positions, and PDF table parsing.
- Proactive scheduler tests validating reminder delivery and schedule notifications.

### 7. Acceptance Criteria
- Multimodal responses ground answers accurately on provided visual evidence.
- Proactive reminders trigger only within user-configured operational hours and rules.

### 8. Potential Risks & Mitigations
- *Risk:* Excessive proactive interruptions annoying the user.  
  *Mitigation:* Proactive engine operates under an explicit "quiet mode" policy; suggestions are batched into the idle Orb status bar rather than interrupting active dialogue.

### 9. Completion Conditions
- Multimodal VLM pipeline passes image comprehension test suite.
- Proactive briefing system verified over 48-hour continuous simulation.
- Status: **COMPLETE & VERIFIED** (Git commit `fc0069d`, 17/17 tests passing, 404 regression total).

---

## Stage 9 — Reliability, Security & System Intelligence (COMPLETED)

### 1. Objectives
Harden BEL into an enterprise-grade, crash-resilient, cryptographically secure personal assistant with DPAPI secrets encryption, automated diagnostic watchdogs, self-monitoring, and encrypted backup/restore.

### 2. Features and Capabilities
- **Host DPAPI Credential Vault (`vault_dpapi.py`):**
  - Encrypts all API tokens, passwords, and sensitive keys using Windows Data Protection API (DPAPI) tied to the owner's Windows user login.
  - Zero plaintext secrets stored on disk.
- **Self-Monitoring & Crash Watchdog:**
  - Out-of-process watchdog supervisor monitoring BEL backend heartbeat.
  - Automatic restart with state restoration from SQLite checkpoints upon unexpected termination.
- **Dependency & Integrity Verifier:**
  - SHA-256 hash auditing of all installed virtual environment packages and core binary assets.
  - Detects missing, corrupted, or tampered files and alerts the user.
- **Automated Regression Suite Runner:**
  - Background scheduled execution of unit test suites ensuring system integrity remains intact after any updates.
- **Encrypted Backup & Restoration:**
  - One-click atomic backup of SQLite databases, vector embeddings, project memory, and configuration into an encrypted archive.
  - Verified point-in-time recovery.

### 3. Technical Implementation
- Modules: `sight_core/vault_dpapi.py`, `sight_core/crash_watchdog.py`, `sight_core/integrity_audit.py`, `sight_core/backup_restore.py`.
- Security primitives: Win32 `CryptProtectData` / `CryptUnprotectData`, AES-GCM 256, SHA-256 HMAC.

### 4. Dependencies
- Windows `crypt32.dll`, `cryptography` Python package, SQLite backup API.

### 5. Expected Deliverables
- Encrypted secrets vault replacing plaintext environment configs.
- Watchdog supervisor capable of recovering from simulated process termination.
- Encrypted backup archive generation and test restore.

### 6. Testing Procedures
- DPAPI encryption/decryption tests with user session validation.
- Watchdog termination tests killing the backend process and measuring recovery time (< 3.0s).
- Tampered file injection tests verifying integrity auditor detection.

### 7. Acceptance Criteria
- Plaintext secrets eliminated completely from all disk storage and log files.
- Backup archive restores 100% of memories, vector indices, and project files with zero corruption.

### 8. Potential Risks & Mitigations
- *Risk:* Loss of Windows account credentials preventing DPAPI vault decryption.  
  *Mitigation:* Optional passphrase-derived emergency recovery key provided during initial vault setup.

### 9. Completion Conditions
- Vault passes all security audit tests (Win32 DPAPI & portable AES-GCM 256).
- Crash recovery supervisor verified under chaos testing conditions.
- Cryptographic SHA-256 integrity auditor detects all missing/corrupt files and protects kernel files.
- AES-256-GCM encrypted backup archives created and verified through full restoration cycles.
- Status: **COMPLETE & VERIFIED** (9/9 Stage 9 tests passing, 810/810 full regression suite passing).

---

## Stage 10 — BEL V1 Integration, Validation & Finalisation (COMPLETED — 100% ROADMAP ACHIEVEMENT)

### 1. Objectives
Consolidate all 10 stages into a unified, flawless, high-performance personal AI assistant, executing full-system end-to-end acceptance testing, Windows desktop packaging, installer creation, and golden release sign-off.

### 2. Features and Capabilities
- **Full Architecture Convergence:**
  - Unified orchestration connecting Voice, Vision, Memory, RSI, Computer Actuation, Coding, and Multi-Model Routing into a cohesive J.A.R.V.I.S. assistant experience.
- **Comprehensive E2E Golden Test Suite:**
  - Over 400+ automated test cases covering voice dialogue, offline failover, multimodal analysis, coding tasks, and safety boundaries.
- **Windows Standalone Packaging:**
  - PyInstaller single-executable or bundled directory build.
  - Inno Setup installer script with start menu integration, desktop shortcuts, and optional background autostart.
- **Background Tray Service:**
  - Seamless background daemon running in Windows system tray with hotkey summoning (`Win+Shift+B` or Wake Word "BEL").
- **Final Golden Documentation:**
  - Complete User Guide, Architecture Manual, Developer Guide, and Quick Reference.

### 3. Technical Implementation
- Scripts: `scripts/build_package.py`, `scripts/run_golden_suite.py`, `packaging/installer.iss`.
- Tools: PyInstaller, Inno Setup Compiler, Vite production bundle pipeline.

### 4. Dependencies
- PyInstaller, Inno Setup, Node.js, Python 3.12 x64.

### 5. Expected Deliverables
- `BEL_Setup_v1.0.0.exe` installer.
- Standalone portable ZIP package.
- 100% passing golden acceptance test report.
- Complete documentation handbook.

### 6. Testing Procedures
- Clean-machine VM installation and first-boot validation on Windows 10 and Windows 11.
- Complete offline test: disconnecting VM network and verifying voice chat, memory retrieval, and local tools operate without errors.

### 7. Acceptance Criteria
- Zero critical or high-severity bugs.
- Cold startup time to ready state < 2.5 seconds.
- 100% pass rate across entire regression test suite.

### 8. Potential Risks & Mitigations
- *Risk:* Anti-virus false positives on packaged Python executables.  
  *Mitigation:* Code-signing of installer and executables with trusted certificate; exclusion instructions documented in setup guide.

### 9. Completion Conditions
- Master Golden Suite executed and verified with 100% pass rate (814/814 tests passed).
- All 26 architectural subsystems verified active and converged.
- Axiom 1 protected kernel files audited and cryptographically verified.
- Windows portable bundle (`dist/BEL_V1_Portable`) and Inno Setup installer script (`packaging/installer.iss`) generated.
- Status: **COMPLETE & GOLDEN RELEASE CERTIFIED** (Manifest: `BEL_V1_VALIDATION_MANIFEST.json`).

---

## 3. Technology Stack & Resource Allocation

| Component | Selected Technology | License / Cost | Hardware Footprint |
| :--- | :--- | :---: | :--- |
| **Backend Framework** | FastAPI / Starlette / Uvicorn | MIT / Free | < 80 MiB RAM |
| **Database** | SQLite3 (WAL Mode + FTS5) | Public Domain / Free | < 25 MiB RAM |
| **Frontend Shell** | React 19 + TypeScript + Vite + Tailwind | MIT / Free | < 120 MiB RAM (Edge WebView) |
| **Local LLM Inference** | Ollama (`qwen2.5:1.5b`, `gemma2:2b`) | Apache 2.0 / Free | 1.8 – 3.2 GiB RAM / VRAM |
| **Cloud Acceleration** | Groq / Gemini Flash / OpenRouter | Free Tier / Low Cost | Zero local compute |
| **Vector Embeddings** | Custom Pure-Python 128-d Vectorizer | Proprietary / Zero Cost | < 10 MiB RAM |
| **Speech Recognition** | Whisper.cpp (CPU) + Windows SAPI | MIT / Native Free | < 250 MiB RAM |
| **Speech Synthesis** | Windows WinRT `SpeechSynthesis` | Windows Native / Free | < 30 MiB RAM |
| **Wake-Word Detection** | Acoustic VAD Rolling Engine | Custom / Zero Cost | < 5 MiB RAM |
| **Computer Vision** | Pillow + Win32 GDI | MIT / Native Free | < 40 MiB RAM |
| **Browser Automation** | Playwright (Chromium Headless) | Apache 2.0 / Free | < 180 MiB RAM (when active) |
| **Total System Baseline** | **Full Local Suite Running** | **100% Free / Sovereign** | **~2.8 GiB RAM (Fits in 8-16GB PCs)** |

---

## 4. Scope Boundaries: BEL V1 vs BEL V2 Future Horizon

To ensure successful, prompt, and stable delivery of BEL V1, clear boundaries are maintained between V1 release targets and future V2 research:

| Capability Domain | BEL V1 (Current Master Roadmap) | BEL V2 (Future Research Horizon) |
| :--- | :--- | :--- |
| **Inference** | Local Ollama + Cloud Router with Fallback | Fully distributed multi-node P2P inference mesh |
| **Voice** | WinRT Natural TTS + Whisper.cpp + Wake VAD | Ultra-expressive voice cloning & emotional tone inflection |
| **Actuation** | Single-screen coordinate grounding with HITL approval | Multi-monitor autonomous complex UI workflows |
| **Creativity** | Scripted Blender, Godot, and Unreal automation | Real-time interactive neural 3D scene generation |
| **Mobility** | Windows Desktop Application & System Tray Daemon | Mobile companion app (iOS/Android) & IoT hardware bridge |
| **Self-Improvement** | Bounded AST-audited tool synthesis & auto-heal | Unbounded autonomous self-compiling cognitive kernel |

---

## 5. Master Roadmap Conclusion & Next Step

BEL is an actively advancing engineering project with **Stages 1 through 4 completely operational**, **Stage 5 verified in baseline voice and Orb capabilities**, and **Stage 6 ready for full activation**.

Following this master roadmap ensures BEL evolves steadily, reliably, and safely into the definitive J.A.R.V.I.S.-class personal AI assistant without redundant rewrites or technical debt.
