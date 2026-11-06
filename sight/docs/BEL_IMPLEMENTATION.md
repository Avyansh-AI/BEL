# BEL implementation and verification — 5 November 2026

This report qualifies the preserved **0.4.1** build. Subsequent opt-in dictation work is documented separately in the [0.4.2 preview report](BEL_DICTATION_PREVIEW.md); the older hour-long test does not qualify the preview.

**Verdict: PARTIAL.** BEL migrates the existing Python application and supplied React source. This report distinguishes observed behavior, regression coverage and unfinished acceptance gates.

## Baseline and scope

Rollback commit: `b859f5690e97e584975e0a5d17d6bca5aa190dd3`, tag `rollback/sight-verified-20261027`, with a verified external Git bundle. [Migration inventory](BEL_MIGRATION.md) records architecture, supplied archive digest, compatibility and rollback. Earlier Phase 1–4 code and historical UI assets remain. The owner reconfirmed official `gemma4:e4b-it-qat`, thinking enabled, temperature 0.2. No cloud inference, quota reset, repository rename, microphone recording or auto-start activation occurred.

## Implemented changes

| Area | Implementation and limits |
| --- | --- |
| Identity/config | `identity.py`, BEL personality, `BEL_*` aliases, new application/package labels, version 0.4.1. Legacy storage, auth and keyring identifiers are retained. |
| Migration | Verified backup before a versioned marker, repeat-safe invocation, path/version/link checks; memories remain in place. |
| Frontend | Supplied React/TypeScript orb at `/`; original pages at `/legacy/`. Real session/CSRF/WebSocket flow, states, history, memory, providers and approval dialogs. Local fonts; no demo replies or hidden cloud speech recognition. |
| Needle | Pinned Apache-2.0 native assets, isolated fixed worker, strict output/schema validation, finite confidence floor 0.7, relevant compact candidates. Proposals cannot execute themselves. Main-model fallback and manual reviewed tools remain available. |
| Execution | Central metadata registry, exact grants, deadlines, durable receipts, duplicate suppression, three-call task budgets, application cooldown, cancellation and interrupted-result handling. Verified completion differs from an unverified attempt. |
| Undo | Durable preimages and exclusive Windows handles for private text create/edit/rename; named target/effect before approval. Refuses changed files, occupied names, replay and restored inode identities. No general filesystem, volume or brightness undo. |
| Applications | Trusted image/process/window checks, reuse and observed launch verification for Notepad/Calculator. No forced close, unsaved-work dismissal, general input injection or self-termination tool. |
| Desktop | Lazy pywebview/WebView2, active/compact/background modes, tray restore/quit, private logs, loopback server, single-instance lock. Presentation-only bridge. Auto-start remains off. |
| Packaging | Windowed `BEL.exe`, fixed hidden worker, compiled React, legacy UI and verified Needle assets. Fresh work directories, source stability checks and embedded-code comparison prevent stale workers. Complete folder SHA-256 manifest. |
| Speech | Actual Windows SAPI WAV rendering, reviewed playback and stop. Local STT and trained BEL wake model are absent; microphone/wake status stays disabled. |
| Existing services | Memory/provenance/privacy/correction/deletion, quotas, durable jobs, owner-local MCP, browser sandbox, declarative Forge and recovery continue. Broader orchestration and executable skill generation are not claimed. |

## Bugs reproduced and repaired

1. React StrictMode duplicated bootstrap claims. The client shares a pending claim, clears fragment credentials and reconnects with authenticated tickets.
2. An empty pywebview bridge object could appear before its methods and crash React. The UI now waits for all three supported methods.
3. Modal focus could scroll the root horizontally by 370 px and clip the orb interface. Overflow/focus handling prevents this; actual browser geometry is checked.
4. Tool panels could reload before execution finished and show stale undo state. They refresh after completion and disable parallel submissions while busy.
5. Undo review showed only opaque IDs. Named targets and remove/restore/rename effects are now presented without exposing saved file contents.
6. Windows newline translation changed bytes and broke file verification. Explicit newline handling preserves requested content.
7. Concurrent edits, partial renames and crashes could undermine file outcomes. Exclusive handles span snapshot through mutation, preimages persist first, and uncertainty is recorded without retry.
8. A pending response could repopulate cleared history. Journal generations reject late writes after deletion.
9. Optional model-summary failure could hide a completed action. Durable tool results survive with a factual fallback response.
10. Repeated Needle cancellation could release serialization before the native worker ended. Worker drainage now holds the lock; the verified library remains locked during loading.
11. Needle's system field wrongly contained behavior instructions; upstream defines environment facts. It now omits instructions. Candidate filtering excludes weak shared-namespace matches; confidence remains unchanged.
12. Frozen Playwright selected an absent bundled browser cache. It now uses the installed current-user cache when no explicit path exists. No browser download or owner-browser attachment happens during a tool call.
13. Incremental PyInstaller builds retained a stale hidden worker. New isolated work directories and embedded-source comparison now detect/prevent it.
14. Compact mode intermittently froze when pywebview changed WinForms `TopMost` from a worker thread. Lifecycle changes now dispatch to the GUI thread, and JavaScript mode notification is asynchronous. Failed close leaves the tray usable.

## Recorded verification

| Verification | Result |
| --- | --- |
| Full Python regression | **516 passed, zero failures or skips**, 164.195 seconds. Two assertions in the preceding run still expected the old user-facing environment variable. Both now check the BEL hint. [Final JUnit](../../audit-tests/20261030-bel/regression-final-002.xml) · [Earlier failure summaries](../../audit-tests/20261030-bel/regression-repair-history.json) |
| Actual React interface | **34/34** passed in 10.094 seconds using Chromium, authenticated HTTP and WebSockets. Includes reviewed memory changes, file create/undo, history and measured active, mobile and compact layouts. Screenshots were inspected. All 13 frontend tests and the production build passed. The dependency audit returned zero reported vulnerabilities. [Live UI results](../../audit-tests/20261030-bel/frontend-final/result.json) |
| Packaged Windows application | **17/17** passed against build 005. Two launches each passed all nine native lifecycle checks. Startup took **3.234 and 3.079 seconds**. Tests exercised tray, webview, compact/background/restore, settings persistence, local WAV rendering, Chromium, bundled Needle, worker restrictions and clean shutdown. The frozen-code comparison matched all 35 main and six worker modules. [Packaged verification](../../audit-tests/20261030-bel/windows-release-005.json) |
| Desktop thread repair | **18 regression tests and 270 real native mode transitions passed**. Two Pythonw lifecycles passed 9/9 each. Only BEL's own windows were exercised. [Desktop review](../../audit-tests/20261030-bel/desktop-review.json) |
| Real Gemma and Forge | **14/14** passed. Coverage included reasoning, instructions, Hindi text, JSON, persistent memory correction/deletion and declarative Forge creation, promotion, invocation and rollback. The cold reply took 23.141 seconds. Subsequent recorded replies took 3.609–10.141 seconds. [Acceptance results](../../audit-tests/20261029-bel/gemma-acceptance-001.json) |
| Gemma integrity | All **five active config and layer blobs** passed full hash checks in 6.969 seconds. Active manifest digest is `ee665637121887cf3befff38abbb1be4ee117c7db867d97a67e29049ecd7e15f`. Verification uses Ollama's active v2 manifest layout. [Integrity report](../../audit-tests/20261029-bel/gemma-integrity-001.json) |
| Needle intent routing | **5/8** baseline cases passed, up from 4/8. **6/10** held-out cases passed. All six negative or unsupported held-out requests fell back safely. Every one of the four positive held-out phrasings missed the 0.7 confidence floor. Neither matrix executed an action. [Baseline](../../audit-tests/20261030-bel/needle-production-002.json) · [Held-out cases](../../audit-tests/20261030-bel/needle-production-heldout-001.json) |
| Undo and application policy | 27 undo/tool regression tests passed, including named reversal previews. The 20 Windows application tests included actual read-only process/window enumeration. Open/focus effects on personal apps were tested with controlled adapters only. [Undo and tool regressions](../../audit-tests/20261029-bel/undo-review-001.xml) |

Earlier packaged builds 001–003 exposed stale worker code, browser-cache selection and intermittent native lifecycle failures. Build 004 passed both startups in 2.828 seconds on this host. Build 005 includes the thread repair. These short startup samples do not establish a sustained speed improvement. The original SIGHT project had no comparable native desktop host.

The first BEL soak preflight observed that Ollama was offline and recorded a failed inference. The fresh run on 4 November completed **509/509 checks over 3,607.640 seconds** on the frozen BEL backend and current official Gemma model. All 60 cycles completed with three planned crash/restarts and zero unexpected server exits. All 12 sampled arithmetic replies were correct. Median reply latency was 6.6015 seconds, with a 7.094-second maximum. Six actual offline browser captures completed, and the final backup/restore checks included BEL conversation history, execution receipts and undo journals. Runtime source and installed dependencies matched their starting hashes. [Full soak result](../../audit-tests/20261104-bel/soak-20261104T164946Z-bb5f24/result.json)

Telemetry recorded 708 samples. GPU memory peaked at 4,405 MiB, GPU temperature at 86 °C and the backend working set at 74.29 MiB. Minimum available host RAM was **91.52 MiB**, with peak host CPU use of 59.04%. This was a heavily loaded shared host. CPU temperature was unavailable from the interfaces used. The passing soak should be assessed alongside that limited RAM headroom.

Independent restoration review passed **27/27 checks**. It verified all 69 backup entries, 67 restored non-database files and 29 database tables. BEL history, execution receipts and undo records matched across original, backup and restore. All 71 source/frontend hashes and 50 installed dependency versions still matched. The maximum health-check gap was 60.937 seconds and the maximum telemetry gap was 5.181 seconds. [Independent review](../../audit-tests/20261105-bel/restore-review.json)

The actual exported ZIP was independently extracted and verified. Its extracted EXE passed **17/17** checks again, including both native lifecycle runs, at startup times of 3.765 and 2.016 seconds. This used the installed WebView2 and Chromium. All 451 archive members, 364 application payload hashes, 49 source hashes, 41 embedded modules and both entry points were checked. Eleven supplied credentials had zero matches in the uncompressed archive and embedded application code. [Archive verification](../../audit-tests/20261104-bel/windows/artifact-integrity.json) · [Extracted application verification](../../audit-tests/20261104-bel/windows/extracted-release.json)

The Windows handoff is `BEL-0.4.1-Windows-x64.zip`, **111,270,507 bytes**, SHA-256 `6b3c30c5028c51555f5afadde8babd477e49bc07342043b2ae87ace3f7abf2ee`. It includes license notices, an application manifest, archive-member hashes and a concise operating guide. Extract the whole folder and open `BEL.exe`.

## Remaining limits

- Needle's positive phrasing coverage is poor. Correct schemas and safe refusal do not make it a reliable general router; thresholds were not lowered to increase pass counts.
- Microphone/STT, valid BEL wake training, device switching, echo protection and voice barge-in remain incomplete. Owner recordings and explicit capture consent are still needed. Playback interruption differs from speech barge-in.
- An additional Windows offline-dictation probe found an installed English recognizer. It produced text for two synthetic WAVs but matched neither sentence exactly, with four word edits across seventeen reference words. No Hindi recognizer was installed. This candidate still needs transcript review, integration and hardware acceptance before enabling capture. [Synthetic probe](../../audit-tests/20261104-bel/voice-probe.json)
- Windows artifact is unsigned; installed WebView2/Chromium were reused. Fresh-account installation and second-machine qualification remain untested.
- Twelve roles remain logical roles. Broad parallel orchestration, independent verifiers, mobile pairing and new proactive metrics/briefings are not claimed.
- Forge remains restricted declarative transformations with review and rollback. Generated executable candidates/dependencies, isolated source patching and promotion need a separate secured implementation.
- General window/input automation needs additional scoped adapters. Browser inspection is an offline sandbox, not a separately authorized general browsing session.
- Optional cloud adapters were preserved; no new cloud inference was sent, and $0 spending limit and rolling ledgers remain intact.

## Provenance and rollback

Needle follows its [official repository](https://github.com/cactus-compute/needle) and [model distribution](https://huggingface.co/Cactus-Compute/needle3), with pinned asset hashes. [Mark-LVI](https://github.com/FatihMakes/Mark-LVI) informed outcome/confirmation/undo/app-identity ideas. Its CC BY-NC 4.0 source was not copied into this MIT application; these implementations are independent. The supplied orb and bundled OFL fonts retain provenance/notices.

Use a separate checkout of `rollback/sight-verified-20261027`; do not reset over BEL work. Restore verified private data into a new directory and inspect before activation. Separate packaged production, development source, private data, skills and verified backups. No self-generated production rewrite occurred.

The implemented subset passed regression, packaged Windows and hour-long stability checks. Next development should improve Needle positive-intent coverage, integrate reviewed local speech recognition, qualify a clean Windows account and add a valid BEL wake model. Executable Forge candidates require a separately secured implementation. Overall readiness remains **PARTIAL** because these requested capabilities are still incomplete.
