# BEL 0.4.2 Preview 2 — work completed to date

**Report date:** 9 November 2026
**Branch:** `bel/offline-voice-preview2`
**Base:** Preview 1 commit `98c8f3120e5f7fc3ce960dcfbe90323e859cacdf`
**Verdict:** **PARTIAL**. The offline English dictation path is materially improved and validated on a licensed read-speech corpus. Hindi accuracy, physical microphone acceptance, BEL wake-word detection, and the configured Ollama endpoint remain unresolved gates.

## What changed

Preview 2 adds a selectable offline `whisper.cpp` CPU recognizer (base/small Q5_1) alongside Windows System.Speech, with pinned runtime/model hashes, explicit local installation, asset validation, process/resource limits, deadlines, cancellation, safe fallback, and no recognition-time downloads or cloud speech. The live backend remains on the existing Python architecture. The selected Gemma preference remains `gemma4:e4b-it-qat` with thinking enabled.

The voice flow now requires explicit microphone/session consent, explicit recording, local transcription, transcript review/editing, and a deliberate Send action. Capture has bounded duration and silence checks, device-change/track-loss cleanup, cancellation, audio level feedback, permission errors, reduced-motion behavior, and fallback warnings. Spoken text cannot submit itself or invoke tools. The original animated orb and text-chat path remain in place.

A real Windows System.Speech end-of-stream defect was reproduced and repaired: the recognizer could clear its audio format after EOF and drop later text. The ASR installer also received a permissions fix after review; existing parent/source ACLs are preserved, with regression coverage. BEL wake-word support is an interface only: wake monitoring stays disabled and no BEL-specific trained model exists.

## Measured recognition

The frozen English evaluation used 80 LibriSpeech recordings from 71 speakers (2,669 normalized scoring words), plus 10 deterministic 10 dB noise variants per engine. On the same clips:

| Engine | English WER | CER | Median latency | Peak sampled working set | Peak sampled private bytes |
|---|---:|---:|---:|---:|---:|
| Windows System.Speech | 61.71% | 43.78% | 1.665 s | 246.0 MiB | 141.7 MiB |
| whisper.cpp base-q5_1 | 7.42% | 3.32% | 2.047 s | 295.8 MiB | 757.5 MiB |
| whisper.cpp small-q5_1 | 5.06% | 2.39% | 5.641 s | 685.9 MiB | 1,083.6 MiB |

Each engine returned all 80 original and 10 noise-variant transcriptions without adapter errors; tested silence/near-silence was rejected. The provisional 15% English WER target was met on this read-speech subset. It does not qualify owner-accent conversation or physical-microphone accuracy. Memory is sampled process-tree usage, not isolated model allocation. GPU attribution was unavailable; CPU inference was explicitly selected.

Hindi was evaluated on 24 human read-speech clips (514 reference tokens). Base scored **101.36% WER / 105.16% CER**; small scored **56.03% WER / 32.64% CER**, with small maximum latency 44.719 s. This is poor Hindi recognition. Speaker diversity is unknown for this mirror subset. Hindi-English mixed speech has no valid test corpus here and remains untested. A synthetic 24-case English formatting/numbers probe is supplementary and does not replace human speech qualification.

## Verification completed

- Backend regression: **648 passed, 0 failed, 0 errors, 0 skipped** (`regression-003.xml`); this receipt predates the final formatting tests and installer ACL regression test.
- Frontend unit tests: **26 passed**; frontend adversarial browser/API checks: **27/27**.
- Existing UI browser checks: **34/34**; live browser-to-ASR checks: **25/25**.
- Frozen Windows speech/native checks: **23/23**; extracted Windows app checks: **17/17**.
- Engine tests: **37 passed**; installer/EOF tests: **30 passed**; acceptance-preparation tests: **34 passed**; installer ACL regression: **7 passed**; formatting benchmark tests: **10 passed**.
- Fresh voice lifecycle soak: **3,600 seconds, 60 cycles, 824/824 checks passed**, no owned child-process leaks, backend private-memory growth 5.059 MiB (below the 64 MiB limit). This run exercised the frozen app and ASR lifecycle; it was not a Gemma chat soak.
- Verified Gemma weight integrity: all five weight files passed hash checks. The normal configured Ollama endpoint was **not ready**: installed Ollama 0.13.0 returned an empty model list and Gemma preflight reported `model_missing`. Therefore fresh Gemma inference/acceptance was not completed in this run. Do not interpret model-file integrity as runtime inference validation.
- The downloaded assets totaled 258,721,752 bytes for whisper.cpp runtime and base/small models; licensed evaluation audio totaled 25,788,548 bytes, below the approved 50 MB limit. No cloud requests were made.

## Readiness matrix

| Capability | Status | Evidence / limitation |
|---|---|---|
| Offline English speech | PASS | Small Q5_1 scored 5.06% WER on the frozen LibriSpeech subset |
| Offline Hindi speech | FAIL | Small 56.03% WER; base 101.36% WER on 24 clips |
| Hindi-English mixed speech | NOT TESTED | No qualifying mixed-speech corpus available |
| Real microphone capture | NOT TESTED | Physical microphone and Windows consent dialog need owner acceptance |
| Orb voice feedback | PASS | Browser checks cover voice state and draft flow |
| Reviewed transcription | PASS | Edit/Send/Discard flow; no speech-triggered actions |
| Wake-word detection | NOT TESTED | Disabled interface only; no trained BEL model |
| Speech cancellation | PASS | Session-scoped cancellation and worker cleanup tests |
| Frozen Windows application | PARTIAL | Extracted package checks pass; no fresh-account or physical mic qualification |
| 3,600-second stability | PASS | 60-cycle prerecorded-audio voice lifecycle soak |
| Gemma live inference | FAIL | Configured Ollama endpoint has no installed model; weight integrity alone passed |

## Security and known limits

The recognizer worker is constrained with a Windows Job Object (1.5 GiB and one active process), fixed arguments, CPU-only mode, and a reduced environment. This is resource containment, not a security sandbox. Disk hashing checks cancellation between reads, but a kernel-blocked storage read cannot be forcibly interrupted; the complete validation path does not have a hard wall-clock guarantee. Pipe output limits apply after collection. The upstream whisper.cpp runtime is a pinned prerelease and its executable is unsigned. Hardware acoustics, echo reduction, native permission prompts, fresh-account install, GPU attribution, and real owner speech remain unverified.

## Packaging, rollback, and next steps

The verified stable 0.4.1 archive remains untouched (111,270,507 bytes; SHA-256 `6b3c30c5028c51555f5afadde8babd477e49bc07342043b2ae87ace3f7abf2ee`). Preview 1 also remains untouched (111,291,871 bytes; SHA-256 `1a65d49fcd1832b6128719af55ac6f7c2feb1e4833fa74b3c2805c3f71915475`). A Preview 2 candidate ZIP was built, but it predates the final auxiliary installer ACL repair; it is not presented as the final release artifact. The rollback tag `rollback/bel-preview1-20261106` points to the Preview 1 base.

Next: re-export Preview 2 with the installer repair, independently verify clean extraction/checksums, complete the current-source regression suite and publication scan, then owner-run the microphone/privacy acceptance checklist. Restore a correctly configured local Ollama runtime and rerun live Gemma acceptance before claiming local chat readiness. Improve Hindi model support and collect an approved mixed-speech corpus before claiming those languages are usable.

Detailed benchmark, setup, hardware acceptance, plan, and security review are in the adjacent files `BEL_SPEECH_BENCHMARK.md`, `BEL_OFFLINE_SPEECH.md`, `BEL_VOICE_HARDWARE.md`, `BEL_PREVIEW2_PLAN.md`, and `BEL_PREVIEW2_SECURITY_REVIEW.md`.
