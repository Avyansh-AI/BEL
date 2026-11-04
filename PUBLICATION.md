# BEL publication and historical SIGHT builds

## BEL source update

The current project is BEL — Behavioral Executive Logic, version 0.4.1. The existing repository retains its SIGHT history. The approved reasoning model is `gemma4:e4b-it-qat` with thinking enabled. Release readiness is **PARTIAL**. The [implementation report](sight/docs/BEL_IMPLEMENTATION.md) and [Windows setup guide](sight/docs/BEL_SETUP.md) describe this source and how to reproduce the one-folder application.

The source update includes the official supplied React frontend, Python changes, exact dependency locks, Windows build recipe and reviewed synthetic verification evidence. Runtime caches, owner data, recordings and credentials are private. Historical SIGHT packages below retain their original dates and scope. The rollback source is `b859f5690e97e584975e0a5d17d6bca5aa190dd3`.

## 27 October source update

The owner authorized updating the existing GitHub repository on 27 October. GitHub now identifies the former `Avyansh-AI/Sight` URL as **`Avyansh-AI/BEL`**; both URLs resolve to the same SIGHT history. This update retains the SIGHT project name and **PARTIAL** readiness verdict. No release tag or production deployment is included.

The current source contains the memory, Forge, installer, official-model identity, dependency, thinking-profile and browser-diagnostics repairs documented in the [completion audit](sight/docs/PHASE4_COMPLETION_20261024.md) and [latest browser report](sight/docs/BROWSER_DIAGNOSTICS_20261027.md). Current regression results are **379 passed, zero failures/skips**, with **16 unchanged UI comparisons**, **30/30 actual browser captures** and **57/57 live application checks**. The owner's approved local profile uses `gemma4:e4b-it-qat`, thinking enabled, temperature 0.2. The combined browser/Gemma soak passed **487/487 checks over 3,605.031 seconds**, with independent restoration verification. This is the preserved SIGHT baseline; publication is deferred while the newly requested BEL migration is implemented.

Source and reviewable test evidence are included. Owner data, credentials, runtime environments, model weights, raw server logs, test databases and backup payloads are excluded; synthetic backup manifests and verification summaries are included. Historical failed tests remain available and are explained in the reports.

The [27 October publication check](audit-tests/20261027-browser/final-build/publication-check-final.json) checks exact staged bytes, supplied-credential exclusion, original UI/earlier-phase preservation and documentation links. The [current source manifest](publication-tests/20261027-update/final-manifest.json) inventories the staged files, excluding those two self-referential output files. This manifest describes source publication, not a new packaged release.

Use the repository's current source or [download the current branch](https://github.com/Avyansh-AI/BEL/archive/refs/heads/main.zip). The `dist/SIGHT-Phase4-Partial.zip` file and `UPLOAD_MANIFEST.json` below are preserved **22 October artifacts**, not manifests or packages for this updated source. Their original results must not be used to qualify the new build.

## Historical 22 October handoff

This repository contains the latest Phase 4 source handoff. Its release verdict remains **PARTIAL**. Publishing the source does not change the recorded readiness verdict or erase failed/historical tests.

- Selected model: official `gemma4:e4b-it-qat`, thinking initially disabled.
- Windows regression evidence: 314 passed, zero failures/skips; 16 UI comparisons, zero changed pixels.
- Official model files passed complete local SHA-256 checks. Live official inference, reasoning and soak qualification are pending because Ollama is currently absent from the build machine.
- Prior uncensored inference/growth/soak reports remain explicitly historical.
- The original repository MIT license is preserved. No reference-repository source code is bundled.
- Credentials, owner-data databases, test databases, model weights, installed environments and raw server logs are excluded.

The [build ZIP](dist/SIGHT-Phase4-Partial.zip) preserves the complete handoff layout. The source tree is extracted from that verified ZIP, with publication notes added to README and byte-preservation rules added to .gitattributes. One historical 151 MB source-symbol index exceeds GitHub's individual-file limit; it is published as `sight/reports/source_symbol_candidates.csv.gz`. Decompressing it reproduces the exact original CSV. The full ZIP also contains the original CSV. This index is metadata, not executable product source or proof of semantic coverage.

[Upload manifest](UPLOAD_MANIFEST.json) records every published file's hash and the compressed-file mapping. The manifest itself is excluded from its own hash list.

Run `Verify-SIGHT.ps1` on Windows after installing the pinned requirements and Playwright browser. Recorded paths inside historical evidence describe the build machine. Audit-only scripts such as `check_phase4_handoff.py` additionally need the preserved earlier phases and private key-exclusion input on that machine; they are not required to run SIGHT.

[Readiness](sight/docs/PHASE4_READINESS.md) | [Tests](sight/docs/PHASE4_TEST_RESULTS.md) | [Official model setup](sight/docs/OFFICIAL_GEMMA.md)

The exported GitHub checkout was separately retested: **314 passed, zero failures/skips**, in 120.65 seconds using the provisioned environment. [Checkout test results](publication-tests/result.json), [raw log](publication-tests/pytest.log), [JUnit](publication-tests/junit.xml).
