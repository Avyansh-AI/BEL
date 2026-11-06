# BEL offline dictation preview — 6 November 2026

**Verdict: PARTIAL.** The 0.4.2.dev1 candidate adds opt-in local Windows recognition to the existing BEL orb, Python backend and desktop host. Speech becomes an editable draft for human review. It never sends a message or invokes a tool on its own. Physical microphone quality and native permission prompts remain unverified, recognition accuracy is limited, and a trained BEL wake model is absent.

## Scope and rollback

Work is isolated on `bel/local-dictation-preview`, based on `8ec3ca007b4aeef1559a280faf404e5af85fe83a`. The verified 0.4.1 application and ZIP remain separate. Owner data, saved model settings, quota ledgers, cloud-provider policies, existing tool permissions and the supplied orb design are preserved. The selected model remains `gemma4:e4b-it-qat` with thinking enabled. No physical microphone, speaker playback, cloud inference or autostart setting was used or activated during this verification.

Rollback means closing the preview and using the preserved 0.4.1 folder, or a separate checkout of the baseline commit. No memory/schema migration is added by this feature. Do not reset a checkout over unrelated work. The preview development environment reuses the pinned stable Python environment through a local ignored junction; this is not a clean-account installation test.

## Changes

- `sight_core/local_speech.py` and `speech_worker.py`: lazy, fixed-program Windows System.Speech workers; installed language discovery; validated mono 16 kHz, 16-bit PCM WAV input; 0.1–20 second recording bounds; serialization, deadlines, cancellation and process/pipe cleanup. Input goes through stdin as data. The worker reads an in-memory WAV and never opens a recording device or evaluates recognized text as code.
- `api.py`: exact-session consent, CSRF checks, session-scoped recognition events, explicit cancellation, replay protection and TCP-disconnect cleanup. The microphone Permissions Policy allows only the primary frontend when the startup option is enabled. Legacy pages remain denied. Up to 512 request IDs per owner session are retained until expiry; the server rejects additional requests rather than evicting cancelled IDs.
- `config.py`, `desktop.py`, `Start-BEL.ps1`: explicit default-off startup switch and environment setting. No new dependency or model download. Installed English/Hindi recognizers are discovered; only en-US exists on the test host.
- `App.tsx`, `belApi.ts`, `voice.ts`, `dictation.ts`: explicit consent, installed-language/device selection, hold-to-talk, bounded silent capture, editable reviewed transcripts, preservation of existing typed drafts, low-confidence warnings and named-request cancellation. Hidden pages, device loss/change and revocation discard pending input. Browser echo-cancellation/noise-suppression constraints are requested but their real acoustic effect is unqualified.
- `Verify-BEL.ps1`: frontend tests/build run before backend tests, so a clean source checkout can serve the frontend during API compatibility tests.
- Preview packaging metadata and export guide distinguish this candidate from the preserved 0.4.1 artifact.

## Reproduced issues and repairs

1. CPython on Windows can block synchronously while writing stdin even when `communicate(timeout=...)` is used. A deliberately stalled child reproduced the old hang. Pipe exchange now runs in an owned thread while the controlling worker can kill the exact child on cancellation/deadline, reap it, join I/O and close handles before accepting another request.
2. Aborting a browser fetch alone did not reliably communicate an intentional stop. Cancellation now targets an exact UUID, drains its worker and records that UUID before a delayed upload can arrive. A stale cancellation cannot stop a different request. A real TCP disconnect also stops its owned worker.
3. A late status/consent response could overwrite newer UI permission state. Connection/consent generations prevent this; late transcripts are rejected after cancellation/revocation.
4. Speech could replace an existing typed draft. Transcripts now append with the same 8,000-character bound, and nothing is automatically submitted.
5. Initial oversized binary pytest parameter IDs exceeded Windows' environment-variable limit. Short semantic test IDs repair the test harness. Three early API-page test failures came from an unbuilt candidate frontend. The verification launcher now builds it first.
6. The full suite initially passed 552 cases and failed one legacy browser assertion expecting the historical word `pending`. That assertion now waits for the outstanding chat reply and checks the actual disabled-speech reason and zero device access. The preserved legacy HTML is unchanged. Raw failed traces remain private because they contain ephemeral test session identifiers.

## Validation

Evidence distinguishes fixture regressions, real local runtime tests and synthetic input. No test used a physical microphone or sent cloud inference. Earlier failed attempts remain accounted for above.

| Verification | Exact result | Evidence |
| --- | --- | --- |
| Full backend regression | 553 passed; zero failures/errors/skips; JUnit elapsed 106.243 s. Includes real Windows stalled-worker cancellation tests and existing memory/backup/Forge/browser coverage, alongside fixture tests. | [JUnit](../../audit-tests/20261106-speech/regression-002.xml) |
| Frontend unit/build | 20/20 passed; TypeScript/Vite build passed in 5.81 s. Audio-device/transport fixtures are simulated. | [Summary](../../audit-tests/20261106-speech/frontend/unit-summary.json) |
| Existing live UI | 34/34; Chromium + real HTTP/WebSockets, 13.125 s; no JavaScript errors/external requests. | [Result](../../audit-tests/20261106-speech/frontend/result.json) |
| Live speech HTTP | 27/27, 5.016 s; actual Windows recognizer, two synthetic WAVs, worker cancellation/disconnect/replay and privacy checks. | [Result](../../audit-tests/20261105-speech/live-http-002.json) |
| Live speech browser | 20/20, 28.500 s; Chromium fake audio device feeding real capture, API and Windows recognition; orb states, editable draft, cancellation and mute. Observed confidence 0.052 triggers the review warning. | [Result](../../audit-tests/20261106-speech/browser-002.json) |
| Frozen speech/native | 23/23, 17.703 s; real EXE, synthetic WAV through authenticated HTTP, separate renderer consent, native modes/tray/shutdown. Recognition 1.094 s. | [Result](../../audit-tests/20261106-speech/native-speech-001.json) |
| Existing frozen Windows suite | 17/17; two native lifecycle runs each 9/9; startup 2.250/2.890 s; declarative worker, rejected executable operation, SAPI WAV, browser sandbox and native Needle. | [Result](../../audit-tests/20261106-speech/native-release-001.json) |
| Actual Gemma acceptance | 14/14 with thinking enabled: reasoning, instructions, JSON, Hindi text, persisted/corrected/deleted memory and generated declarative Forge lifecycle. | [Result](../../audit-tests/20261106-speech/gemma-002.json) |

Gemma initially reported the local runtime offline. The existing local-runtime helper started it; the first 40-second wait expired, then the same process became healthy without a restart. Ollama 0.40.9 served the selected model. The first cold reply took 17.062 s; the other twelve timed cases ranged from 3.141 to 8.609 s. This short run is not stability or latency-distribution qualification. The host had little free RAM during combined work, so no speed improvement is claimed. The failed preflight is retained as [gemma-001.json](../../audit-tests/20261106-speech/gemma-001.json).

## Windows handoff

The preview archive is `BEL-0.4.2-preview1-Windows-x64.zip`, **111,291,871 bytes**, SHA-256 `1a65d49fcd1832b6128719af55ac6f7c2feb1e4833fa74b3c2805c3f71915475`. It contains 451 members, including 364 application files and notices for 55 distributions. Packaging verified 51 source files, 37 desktop modules, six worker modules and both entry points. [Export verification](../../audit-tests/20261106-speech/artifact-export.json)

Independent review rechecked the exact ZIP, every member/payload/source hash and both entry points. Eleven supplied credentials had zero matches across uncompressed files and 2,205 embedded Python modules in UTF-8/UTF-16 encodings. The independently extracted application passed **17/17 Windows checks**, with startup times of **2.234/1.969 s**. The staged-source scan also passed with zero credential matches; private caches, owner data, audio, raw logs and failed tracebacks are excluded from publication. [Independent artifact review](../../audit-tests/20261106-speech/artifact-independent.json) · [Extracted EXE tests](../../audit-tests/20261106-speech/extracted-native.json)

Extract the whole folder and open `BEL.exe`. To test optional dictation, launch `BEL.exe --local-dictation`, then enable session consent in Settings. Keep the preview separate from the previous installation. The application still requires installed WebView2 and a separately running local Ollama service for Gemma. The ZIP is unsigned and has not been qualified on a fresh Windows account. [Setup and privacy behavior](BEL_SETUP.md#tools-and-voice)

The direct Windows recognizer returned text for two synthetic phrases but matched neither exactly: **5 word edits across 17 reference words**, or 29.4% word error on this tiny sample. This is evidence of integration, not acceptable general dictation accuracy or a human-voice benchmark. The expected phrases were never supplied to its unconstrained dictation grammar.

## Remaining gates

Physical microphone permission/capture, accents, device switching under actual hardware failure, echo protection, native WebView2 permission UI and sustained dictation need owner-controlled testing. Hindi recognition requires a compatible installed recognizer. The supplied corpus is too small to characterize speech quality. A trained BEL wake model and owner enrollment remain unavailable; background mode does not listen. This preview has not run a fresh 3,600-second stability test. The older 0.4.1 soak remains historical evidence for that artifact only.

Existing broader limits continue: inconsistent positive Needle coverage, fresh Windows account qualification, general desktop/browser control, mobile pairing and separately secured executable Forge generation. See the [0.4.1 implementation report](BEL_IMPLEMENTATION.md) for those boundaries. Next steps are a representative owner-approved speech benchmark and hardware acceptance before expanding voice capabilities or treating this preview as production-ready.
