# Official local model repair and verification — 23 October 2026

**Local model acceptance and the 23 October one-hour soak: PASS within the cases below. Overall Phase 4 release: PARTIAL.** A subsequent advisory scan found vulnerable Certifi/Pillow pins. See the [24 October dependency repair](DEPENDENCY_SECURITY_20261024.md) for the changed environment and its separate requalification; this soak does not qualify those later dependencies.

This follows the [repository repair audit](REPOSITORY_AUDIT_20261023.md). The working checkout is based on commit `372df995004bf640f352e06c8ea25c942b468663`; changes and evidence remain local. The published ZIP is unchanged. No cloud inference, paid activation, quota reset, owner-data deletion or remote repository write occurred.

## Plan and actual repair

Restore a verifiable local runtime, check the installed owner-selected model, reproduce adapter failures, repair the narrow cause, run real model acceptance, run the full regression/application checks, then qualify the same source with a new 3,600-second soak. Do not change weights, substitute the old uncensored model or count mocked inference as live acceptance.

Ollama was absent at the end of the first audit. The official Windows standalone v0.40.9 archive was downloaded from the [Ollama release](https://github.com/ollama/ollama/releases/tag/v0.40.9), checked against the release's SHA-256 and extracted into the existing expected per-user installation location. Archive: 1,586,281,618 bytes, SHA-256 `c35019c95679eae1cb28fda4732a7c97978b9fbcbd8adfb5cbcc8fe7c161ea0b`; 80 extracted files, 2,230,815,247 bytes. No PATH or startup entry was changed. [Runtime restoration evidence](../../audit-tests/20261023-local-model/runtime-restore.json).

The existing launcher starts the service on `127.0.0.1:11434`, with cloud disabled, one loaded model and one concurrent inference request. The selected model remains **`gemma4:e4b-it-qat`**, thinking disabled, using the existing `D:/Ollama Models` store. All six manifest-referenced blobs passed full SHA-256 checks; no weights were downloaded or rewritten. The primary manifest digest is `ee665637121887cf3befff38abbb1be4ee117c7db867d97a67e29049ecd7e15f`. The legacy registry wrapper has a different, expected digest; it contains the primary manifest as a layer.

The first real acceptance attempt exposed a blocker: `LocalAdapter._metadata_health()` required the literal text `e4b` in metadata fields where this official model instead reports `4B_dequant_qat_it_hf`. Valid installed weights were rejected before inference. Conversely, changing the model digest and adding a convincing display name could satisfy the old name-only check. Both failures were reproduced and retained in the evidence.

`sight_core/models.py` now verifies this exact selected official tag against its qualified manifest digest, Q4_0 quantization and architecture identity: `gemma4`, 7,463,013,674 parameters, 42 blocks and embedding length 2,560. A future replacement of this tag fails closed until explicitly reviewed. Eight new regression cases use captured actual runtime metadata and reject changed identity fields or a spoofed name. Existing aliases retain their prior behavior; this is not general certification of arbitrary model aliases.

Sampling/context/output limits are unchanged. The repair addresses model recognition and validation; it does not claim to increase the model's inherent intelligence. Thinking-enabled quality, vision and audio-model inference were not qualified by these text tests.

## Exact tests and evidence

| Test | Actual result | Evidence |
| --- | --- | --- |
| First live attempt | Blocked by incorrect metadata rejection; no inference claimed | [Result](../../audit-tests/20261023-local-model/acceptance-first.json) |
| Identity reproductions before repair | **2 failed, 10 passed**, 1.35 s | [Log](../../audit-tests/20261023-local-model/identity-before.log), [JUnit](../../audit-tests/20261023-local-model/identity-before.xml) |
| Focused identity/provider/security regressions after repair | **113 passed**, 12.27 s | [Log](../../audit-tests/20261023-local-model/identity-after.log), [JUnit](../../audit-tests/20261023-local-model/identity-after.xml) |
| Live official-model acceptance | **14/14 passed**, real local inference | [Raw answers, timings, hashes and Forge evidence](../../audit-tests/20261023-local-model/acceptance-after-identity.json) |
| Complete regression suite in checkout's freshly installed environment | **332 passed, 0 failed, 0 skipped**, 206.76 s | [Log](../../audit-tests/20261023-local-model/final.log), [JUnit](../../audit-tests/20261023-local-model/final.xml) |
| Original interface | **16 comparisons, zero changed pixels**, eight states at desktop/mobile sizes | [Desktop](../../audit-tests/20261023-local-model/final-ui/metrics_1440x900.json), [Mobile](../../audit-tests/20261023-local-model/final-ui/metrics_390x844.json) |
| Live application smoke | **57/57 checks passed**, real launched backend | [Result](../../audit-tests/20261023-local-model/live_phase4_20261023T092149Z.json) |
| Fresh current-model/current-backend stability before the later dependency update | **PASS**, 3,602.953 s, 60 cycles, 468/468 checks | [Progress](../../audit-tests/20261023-local-model/soak_progress.json), [Run](../../audit-tests/20261023-local-model/soak-20261023T164224Z-e09e3a/result.json) |

The 332-test suite includes the earlier 314 tests, ten first-audit regressions and eight identity cases. It overlaps the live smoke in wall time, so its duration is not comparable to an isolated speed benchmark. One existing Starlette/httpx deprecation warning remains.

The 14 live cases cover exact response instructions, arithmetic, a sequential discount/tax calculation, time budgeting, logical entailment and non-entailment, a Python expression, Hindi text comprehension, structured JSON equality, a professional-tone screen, persisted memory recall, corrected memory recall, deletion followed by non-recall, and a complete **declarative** Forge lifecycle. Minor outer formatting is normalized for exact-answer grading and is disclosed in the raw record. The tone screen is a narrow language-style check, not a general reasoning score.

Forge actually used the local model to generate a deduplicate-and-sort transformation. Its candidate passed validation and tests, was explicitly promoted in the isolated synthetic harness, invoked twice, superseded by a second declarative version, rolled back and invoked again. No executable skill or owner skill was activated. Memory tests reopened persistent storage and correctly returned `cobalt`, then `jade` after correction, then `UNKNOWN` after deletion.

The 57 smoke checks exercise the real Windows launcher, HTTP/WebSocket Gemma response, local-only policy, memory compaction/lineage/restart/correction/deletion, exact home response bytes, reviewed local adapters, immutable artifact downloads/hashes and reminders. Actual Chromium inspected offline owner-supplied HTML; actual Windows speech rendered a WAV. Six external connector contract pairs are explicitly labeled simulations in the record; they are not live camera/device/account integrations. Speech recording/playback and remote website interaction are not qualified by these checks.

## Performance and stability

The cold first acceptance request took **15.735 s**. The remaining twelve individually timed model requests took **0.703–2.312 s**; the Forge generation request has lifecycle evidence but no separate latency measurement. These are small acceptance prompts, not a general workload benchmark. Post-acceptance observation showed 4,421 MiB GPU memory used out of 8,188 MiB on an RTX 4060 Laptop GPU; that observation is not a measured peak. The fresh soak records its own CPU/RAM/GPU telemetry and recovery events.

The completed soak used isolated synthetic data, real local inference every five cycles, scoped transport outages, deliberate termination/restart of its own backend, task receipts and a final full-data backup/restore. All 468 checks passed, including three planned crash/restarts, interrupted-task non-replay and restoration of all 60 output files. There were no unexpected backend exits. All 12 real answers were correct; median response time was 8.797 s and maximum 22.844 s. Source and dependency hashes stayed unchanged during the run. An earlier runtime no longer answered after a chat pause, so the launcher was restarted before this uninterrupted test; no unobserved cause is asserted. The old uncensored-model soak does not qualify this build.

The 708 telemetry samples measured peak GPU memory of 7,518 MiB, peak GPU temperature of 62 C, peak host CPU of 53.71%, and peak backend working set of 72.25 MiB. Available host RAM fell to 156.12 MiB: the machine was under substantial memory pressure. Host/GPU readings include other applications; they are not solely SIGHT consumption. CPU temperature was unavailable. Functional stability passed under this workload, but these readings do not establish comfortable capacity for additional parallel agents or voice models.

## Changes, limitations and next steps

Product changes in this phase are confined to official model identity validation. Added `scripts/official_gemma_acceptance.py` records an immutable test plan, visible responses, timings, exact source hashes and declarative Forge lifecycle results. The existing smoke/soak scripts accept an explicit evidence directory so new runs preserve historical publication evidence. No UI or dependency pin changed.

The runtime restoration, verified official-model inference, regression suite, live local smoke and this full-duration soak close their specific blockers for the tested environment. Overall release readiness remains **PARTIAL**: the subsequent dependency update needs separate qualification, and fresh Windows-account setup, complete semantic reference coverage and external binary advisory coverage remain open. The broader requested roadmap also remains incomplete: executable Forge needs a separately secured runtime; microphone/STT/playback/interruption and wake enrollment need implementation, runtime and consent; interactive desktop/remote browser tools need their bounded implementation and authorization; expanded orchestration and disposable-worktree code repair need separate validation. The existing 12 roles remain logical roles, not independent model processes.

Next, qualify the security dependency update, then implement subsequent increments against that baseline. Do not declare the broader upgrades production-ready, replace the source ZIP, promote generated executable code or push this checkout without the required owner approval.

To repeat local acceptance without replacing this evidence, use a new output name and run model tests sequentially from the Git root:

```powershell
.\sight\.venv\Scripts\python.exe .\sight\scripts\official_gemma_acceptance.py --output audit-tests\new-run\acceptance.json
.\sight\.venv\Scripts\python.exe .\sight\scripts\phase4_smoke.py --evidence-directory audit-tests\new-run
.\sight\.venv\Scripts\python.exe .\sight\scripts\phase4_soak.py --seconds 3600 --model gemma4:e4b-it-qat --evidence-directory audit-tests\new-run
```
