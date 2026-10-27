# Repository audit and first repair phase — 23 October 2026

**First repair phase: PASS within the tested scope. Overall Phase 4 release: PARTIAL.** The existing regression suite passed, reproduced defects were repaired, and the expanded suite passes. This is not certification of official Gemma inference, an executable Forge, microphone input, remote browser control, or the broader requested roadmap. Local-model verification is the next phase.

The audited checkout is `github-publish/Sight`, based on Git commit `372df995004bf640f352e06c8ea25c942b468663`. Changes remain local. Nothing was pushed, no release was published, and the existing ZIP/upload manifest remain historical publication artifacts. Earlier Phase 1–4 directories, original HTML, references and owner data were preserved.

## Scope and engineering plan

The workspace contains the original manual and HTML, extracted references, `Reference.zip`, earlier phase directories, and the Git checkout. The checkout contains root launchers, `sight/sight_core`, `sight/apps/ui`, `sight/tests`, `sight/scripts`, documentation and historical evidence. Its Python backend and exact UI were retained.

Reviewed README, PLAN, PUBLICATION, Phase 4 architecture/audit/readiness/test/fix documents and the existing manual text. Inspected the FastAPI HTTP/WebSocket boundary, model/router and quota policies, SQLite stores, memory, declarative Forge, durable jobs/receipts, local MCP, capability workers/browser/speech adapters, filesystem/session controls, configuration, launchers and backup/release selection. The manual's historical instruction to build from scratch was not followed: the owner's current request explicitly requires preserving this implementation.

The sequence was: establish a baseline; reproduce concurrency/crash/installation defects; make bounded repairs; run focused regressions; rerun the complete suite from the repository root; install from pinned offline wheels into a fresh environment; inspect the selected local model without changing its weights or selection. The reference repositories were not re-extracted or executed; their earlier inventories remain provenance evidence, not proof that every reference feature is implemented.

## Reproduced defects and repairs

| ID | Reproduction and root cause | Repair and evidence |
| --- | --- | --- |
| A1 | A memory context read a preference before an atomic correction and an episode afterward, mixing revision 1 and revision 2. Both local and cloud-filtered context failed. | `sight_core/memory.py` now constructs preferences, ranked matches, lineage and expiry from one read transaction with one clock/cache. Two real SQLite writer-interleaving regressions pass. |
| A2 | Expiry cleanup selected an expired ID, a concurrent writer renewed that preference, then cleanup deleted the renewed record. | Selection, transitive deletion, index maintenance and audit events now share one immediate write transaction. A separate writer at the transaction boundary retains its renewed preference. |
| A3 | An injected SQLite error or real child-process exit during cleanup left earlier deletions committed, including summaries, indexes and events. | The same atomic cleanup transaction rolls the entire operation back. Separate exception and `os._exit(89)` crash regressions compare all five affected tables before/after. |
| A4 | Windows installation changed the caller's current directory on failure and resolved explicit relative input paths from the application directory. | `scripts/install.ps1` resolves inputs in the caller's directory and uses `Push-Location`/`finally`/`Pop-Location`. Missing-input and venv-failure tests pass; a real installation with relative wheel/cache paths confirms success and caller-location preservation. |
| A5 | Forgetting skill `text_a` also removed `textxa` provenance because SQL `LIKE` interpreted `_` as a wildcard. | `sight_core/forge.py` matches the exact literal skill namespace. The surviving skill retains promotion/invocation links and remains callable. |
| A6 | Two simultaneous Forge invocations both read an initial use count of zero and recorded zero reuses. | Usage accounting evaluates the reuse increment inside the atomic SQL update. Two real worker invocations now record 2 invocations, 1 reuse, 0 failures. |
| A7 | Four existing child-process crash/single-instance tests failed from the repository root with `ModuleNotFoundError`; they inherited the caller's directory. | The tests explicitly launch child Python processes in the package root. The entire expanded suite now passes from the Git root. |

No schema migration, dependency change, provider-policy change, new executable skill authority or UI modification was required. Existing privacy/project filters, memory citations, immutable Forge versions, scoped grants and deletion propagation remain in force.

## Exact test results

All results below were executed during this pass on Windows 11, Python 3.12.5. Provider/model fixtures are distinguished from actual local SQLite, child-process, Chromium and Windows speech-to-WAV operations.

| Test | Result | Evidence |
| --- | --- | --- |
| Initial invocation from Git root | **310 passed, 4 failed**, 95.83 s; all four were child import failures | [Raw log](../../audit-tests/20261023-first-repair/root-invocation-before.log), [JUnit](../../audit-tests/20261023-first-repair/root-invocation-before.xml) |
| Unmodified documented baseline, cwd `sight` | **314 passed, 0 failed, 0 skipped**, 81.75 s | [Raw log](../../audit-tests/20261023-first-repair/baseline.log), [JUnit](../../audit-tests/20261023-first-repair/baseline.xml) |
| New memory/installer reproductions before repair | **7 failed**, 1.66 s | [Raw log](../../audit-tests/20261023-first-repair/repair-before.log), [JUnit](../../audit-tests/20261023-first-repair/repair-before.xml) |
| Memory/installer/learning/concurrency checks after repair, Git-root invocation | **48 passed**, 13.61 s | [Raw log](../../audit-tests/20261023-first-repair/repair-after.log), [JUnit](../../audit-tests/20261023-first-repair/repair-after.xml) |
| New Forge reproductions before repair | **2 failed**, 0.92 s | [Raw log](../../audit-tests/20261023-first-repair/forge-before.log), [JUnit](../../audit-tests/20261023-first-repair/forge-before.xml) |
| Forge and installer checks after repair | **5 passed**, 1.83 s | [Raw log](../../audit-tests/20261023-first-repair/forge-installer-after.log), [JUnit](../../audit-tests/20261023-first-repair/forge-installer-after.xml) |
| Complete expanded suite, Git-root invocation | **324 passed, 0 failed, 0 skipped**, pytest 82.81 s; outer process 85.218 s | [Result](../../audit-tests/20261023-first-repair/final.json), [raw log](../../audit-tests/20261023-first-repair/final.log), [JUnit](../../audit-tests/20261023-first-repair/final.xml) |
| Exact UI visual checks | **16 comparisons, 0 changed pixels** across eight ring states at desktop/mobile sizes | [Desktop metrics](../../audit-tests/20261023-first-repair/final-ui/metrics_1440x900.json), [mobile metrics](../../audit-tests/20261023-first-repair/final-ui/metrics_390x844.json) |
| Fresh environment offline installation and runtime check | **PASS**, 74.719 s; 39 pinned local wheels; installer exit 0, runtime exit 0 | [Result](../../audit-tests/20261023-first-repair/offline-install.json), [installer log](../../audit-tests/20261023-first-repair/offline-install.log), [runtime log](../../audit-tests/20261023-first-repair/offline-runtime.log) |
| Installed dependency consistency | `pip check`: **No broken requirements found** | Also recorded by the real installer log |

Ten regression cases were added. The new relative-path/venv-error case complements the nine failing reproductions. One existing Starlette/httpx deprecation warning remains; no warning was suppressed or dependency updated simply to hide it.

The full suite includes real backup/restore to new directories, hash/tamper rejection, memory lineage/correction/deletion, task crash recovery without duplicate file writes, Forge stage/promotion/invocation/rollback, API/session/CSRF/WebSocket boundaries, one-use approval/injection tests, native Chromium sandbox checks and actual offline browser/speech workers. Model/provider replies, OAuth and hardware contracts in that suite remain fixtures or explicitly labeled simulations. They do not qualify live cloud access, live Gemma, microphone capture or external accounts.

The fresh installation used a new application copy and virtual environment under excluded `test-data/repository-audit-20261023`. It used the current Windows account and an already provisioned Chromium cache. Its runtime check exercised the real copied backend, owner session, local-only default, explicit missing-model status, 212-entry guidance index and offline Chromium. It was not a fresh-account installation and did not install into the owner's active data directory.

## Implemented and verified boundaries

- The existing single FastAPI backend, authenticated local HTTP/WebSockets, local-only defaults and bounded tool reviews remain functional in the regression scope.
- Memory retains source references, project/privacy filters, corrections, expiry, transitive summary invalidation and recoverable backups. Context is now internally consistent across concurrent edits. Snapshot consistency does not revoke a model request that already received context before a later correction.
- Forge remains a restricted declarative text interpreter with test evidence, explicit promotion, immutable versions, invocation tracking and rollback. **Generated executable skills are not implemented or certified.**
- Jobs retain durable dependency plans, budgets, receipts, checkpoints and conservative interrupted-model handling. The 12 roles are logical roles sharing the runner, not 12 independent agents.
- Browser support is isolated owner-supplied HTML with scripts/network disabled. Speech support renders a local WAV; it does not listen, automatically play speech or enroll a wake phrase.
- Recovery verifies backups/snapshots and restores data to new directories. This audit did not implement autonomous code repair or promote a generated production repair.

## Model, resources and remaining release gates

The selected model stays `gemma4:e4b-it-qat`. A fresh read-only check verifies all six installed blobs against their manifest hashes (6,146,502,701 bytes total). The official tag uses the primary manifest under `manifests-v2`; the legacy registry manifest is a compatibility wrapper that includes that manifest as a layer. Its different file hash is not a changed model. [Inventory](../../audit-tests/20261023-first-repair/model-inventory.json).

At the end of the first repair phase, the adapter reported `offline`: no Ollama executable at the expected locations or on PATH and no responding loopback runtime. The old `D:/Installers/OllamaSetup.exe` reports version 0.13.0 and was not installed as a substitute for a current runtime. Runtime restoration and actual official-model quality tests belong to the next sequential phase; their results must be recorded separately.

Hardware inspection reports an NVIDIA RTX 4060 Laptop GPU with 8,188 MiB total VRAM and driver 617.42. Regression duration and installation duration above are measured, but they overlapped and are not an isolated performance benchmark. No current-model inference latency, loaded VRAM, sustained RAM/CPU or stability verdict is claimed here. No cloud inference requests were made, no paid services enabled and no quota ledgers reset.

Remaining gates: actual official-model inference/reasoning/JSON/memory recall; a fresh 3,600-second current-model/current-backend soak; fresh Windows-account qualification; executable Forge isolation/promotion design and implementation; opt-in STT/microphone/playback/barge-in and owner recording; bounded interactive windows/screenshots/input/file organization; separately authorized external browser sessions; broader orchestration and disposable-worktree recovery; unresolved semantic reference coverage and external runtime advisory coverage. Optional ChatGPT owner sign-in and remote devices/accounts remain unverified.

The first repair phase has no observed critical regression after retest. **Overall verdict remains PARTIAL** until the mandatory Phase 4 gates pass. Next: restore the official local runtime, verify the exact selected model with real benchmarks, then advance memory/Forge and opt-in interactions without treating experimental work as a production release. Do not push these changes or replace the published ZIP without owner approval.
