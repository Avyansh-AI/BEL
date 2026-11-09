# BEL release gates

The `bel/offline-voice-preview2` branch continues the preserved `bel/local-dictation-preview` baseline with default-off 0.4.2.dev2 offline voice. See the [Preview 2 report](sight/docs/BEL_PREVIEW2_REPORT.md), [engineering sequence](sight/docs/BEL_PREVIEW2_PLAN.md) and [hardware acceptance](sight/docs/BEL_VOICE_HARDWARE.md). Recognition quality, current packaged validation and a fresh voice lifecycle stability run are separate gates; physical microphone and native consent observations require the owner. Earlier 0.4.1 and Preview 1 evidence remains historical.

The current handoff uses the supplied React orb, the existing Python backend, official Gemma with thinking, the reviewed Needle adapter and the Windows desktop host. The [implementation report](sight/docs/BEL_IMPLEMENTATION.md) records each gate and its evidence. The [setup guide](sight/docs/BEL_SETUP.md) covers the executable and the source build.

1. Preserve existing data and the tagged source rollback, integrate identity and UI, and exercise exact owner-approved tools through real HTTP and WebSockets. Completed.
2. Verify packaged workers, tray lifecycle, compact and background modes on Windows. Build 005 passed all 17 checks. A clean Windows account remains a separate gate.
3. Run the full backend suite, real UI, native Needle and local Gemma. Backend 516/516 and UI 34/34 passed. Needle positive-intent coverage remains partial.
4. Exercise the frozen BEL build with Gemma, approved tools, browser captures, controlled crashes and a verified restore for at least 3,600 seconds. Completed on 4 November with 509/509 checks over 3,607.640 seconds. Host RAM headroom remains a measured constraint.
5. Publish the reviewed source and evidence after the private-data scan. The source was pushed as 2a8e2ae, with the final soak and handoff evidence following. Retain local model data and model caches outside Git.
6. Subsequent development covers local speech recognition and valid wake enrollment, routing accuracy, clean installation, broader bounded tools and separately secured Forge development.

## Historical SIGHT Phase 4 test plan and scope

27 October follow-up: repair the browser failure diagnostic boundary, preserve exact approval/sandbox/network/retry behavior, verify with real worker processes and Chromium, then run a new hour with periodic offline browser captures immediately after actual Gemma inference. Completed so far: **379 regressions, 30/30 real browser captures, 57/57 live application checks**. The combined soak passed **487/487 checks over 3,605.031 seconds**; independent review verified every restored artifact and both databases. The requested BEL migration follows this baseline. See [current browser audit](sight/docs/BROWSER_DIAGNOSTICS_20261027.md). Earlier evidence below predates these worker changes.

26 October evidence review: [repository repairs](sight/docs/REPOSITORY_AUDIT_20261023.md), [official-model verification](sight/docs/LOCAL_MODEL_AUDIT_20261023.md) and [dependency/thinking-profile qualification](sight/docs/DEPENDENCY_SECURITY_20261024.md) have recorded results. The current build passed 338 regressions, 14/14 live acceptance, 57/57 live application checks and a new 3,601.906-second soak with 468/468 checks on 24 October. Source and dependency hashes still match. The owner approved the thinking profile after its 60/60 benchmark. Remaining release limitations include an unexplained intermittent browser screenshot failure, severe shared-host memory pressure and fresh-account qualification. See the [consolidated report](sight/docs/PHASE4_COMPLETION_20261024.md) for the broader capability gaps; they remain separate from the completed stability test.

Detected workspace: original manual/PDF and HTML, eight extracted reference repositories, preserved Phase 1–3, separate Phase-4 build.

1. Reconcile every current archive entry and per-file license observations; retain historical inventories separately. Distinguish symbol candidates, manual requirements and executable capabilities.
2. Reproduce Windows filesystem, SQLite, release manifest, runtime-boundary and logging bugs; add regression tests before repairs.
3. Preserve the exact UI and earlier builds. Verify local HTTP/WS, owner approvals, data recovery, task idempotency, offline behavior and provider quota fixtures.
4. Use the owner's selected official `gemma4:e4b-it-qat` model. Preserve historical uncensored and failed non-thinking diagnostics; do not apply their results to the current thinking profile. Ollama is restored and live acceptance is recorded. No paid/cloud inference.
5. Measure a real one-hour soak with inference, scoped outages, owned-server crash/restart, durable jobs, telemetry and final full backup/restore. Do not call shorter or failed runs an hour.
6. Repeat the bounded growth benchmark, check curator archive/restore/deletion, install from pinned offline wheels in a new environment, and record external runtime/dependency/license inventories.
7. Produce audit, fixes, raw tests and a precise readiness verdict. Package only verified source/evidence, scan for supplied credentials, and verify earlier-phase preservation.

Full certification also requires fresh Windows-account qualification, dependable model behavior and the remaining semantic/integration gates. Optional/blocked statuses are not passes. Do not create an integrated release tag or begin owner wake enrollment while the verdict is PARTIAL.
