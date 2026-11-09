# Preview 2 architecture inventory and verification plan

Inspected 7 November 2026. Development branch: `bel/offline-voice-preview2`, based on Preview 1 commit `98c8f3120e5f7fc3ce960dcfbe90323e859cacdf`. Local rollback tag: `rollback/bel-preview1-20261106`. Stable main remains `8ec3ca0`; the 0.4.1 and Preview 1 archives are preserved separately.

## Existing implementation

- Python FastAPI: `sight_core/api.py` owns authenticated sessions, CSRF, WebSocket state, consent, exact-request cancellation and replay bounds. `local_speech.py` controls disposable fixed System.Speech workers; `speech_worker.py` reads only supplied in-memory WAVs.
- React/TypeScript: `App.tsx`, `voice.ts`, `dictation.ts` provide explicit hold-to-talk, bounded PCM capture, draft handling and cancellation. The supplied `Orb.tsx` artwork and CSS remain the visual baseline.
- Native Windows: `desktop.py`, `runtime.py`, PyInstaller spec and source launchers provide WebView2, tray, background/compact modes and fixed workers. Audio capture is off by default.
- Existing Gemma thinking settings, provider policies/quotas, memory, declarative Forge, Needle, browser tools and recovery are outside this change's scope and remain regression gates.

Fresh baseline: 553 backend tests passed (128.38 s console elapsed), 20 frontend tests passed (217.0022 ms). Evidence is in the private development cache until curated with final results. No physical microphone was opened.

## Implementation order

1. Evaluate pinned CPU-only Whisper models on a frozen, licensed recorded-speech subset; record WER/CER, latency, working-set peaks and GPU observations. Compare with System.Speech and document sample-selection limits. No test references enter recognizer prompts.
2. Add an isolated engine interface with explicit assets, integrity verification, selectable Windows fallback, supported-language checks and visible fallback reasons. No runtime downloads, cloud speech or automatic command execution.
3. Repair permission/device and draft lifecycle gaps, add persistent reviewed speech draft and Send/Discard controls, scope state events to capture/request IDs and preserve text-only operation.
4. Run adversarial unit/integration tests, real browser/speech checks, Gemma and earlier-capability regressions. Build the new whole-folder Windows preview and verify the actual extracted artifact.
5. Run a new isolated 3,600-second voice lifecycle soak with fixed audio, process/resource telemetry and cleanup checks. Prepare owner-run hardware evidence rather than claiming physical-microphone acceptance.
6. Add a disabled wake-engine interface and document BEL-specific training requirements; no background capture or placeholder trained model.

Owner approval received for the pinned whisper.cpp CPU runtime and base/small quantized models (258,721,752 bytes total), plus up to 50 MB of licensed evaluation audio. Models/corpus stay outside Git and the stable application. Provisioning must be an explicit command with integrity checks; recognizer requests must never download assets.

## Selection basis to evaluate

[whisper.cpp](https://github.com/ggml-org/whisper.cpp) supports CPU inference and quantized models with a standalone native runtime. [faster-whisper](https://github.com/SYSTRAN/faster-whisper) supports CTranslate2 CPU int8, but adds a Python/native dependency stack. The first measured candidate is whisper.cpp's pinned Windows CPU runtime plus multilingual base/small Q5_1 models, selected for isolated subprocess integration and zero ASR GPU allocation. This is a candidate choice, not an accuracy or performance verdict. The selected upstream Windows bundle is pre-release b5454 (commit `d1be6fde11ac6e0407606b4e42fe72d34add8037`); its pre-release status must remain visible in final qualification.
