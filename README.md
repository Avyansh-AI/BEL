# BEL — Behavioral Executive Logic

BEL is Avyansh's local-first Windows assistant, migrated from SIGHT using the supplied animated-orb React interface and the existing Python backend. It retains persistent memory, provider policies, durable tasks, reviewed tools, declarative Forge skills and recovery. The selected reasoning model remains **`gemma4:e4b-it-qat` with thinking enabled**.

**Readiness: PARTIAL.** This branch adds an opt-in local-dictation development preview (0.4.2.dev1). Recognition accuracy, physical-device qualification, wake detection, inconsistent Needle confidence and fresh-account installation remain incomplete. Read the [dictation report](sight/docs/BEL_DICTATION_PREVIEW.md) for current tests and the [0.4.1 implementation report](sight/docs/BEL_IMPLEMENTATION.md) for the preserved release. Earlier stability evidence does not qualify this preview.

## Run BEL

Follow the [Windows setup guide](sight/docs/BEL_SETUP.md). Keep `BEL.exe`, `BEL-worker.exe` and `_internal` together. The application opens an authenticated local window, supports compact/background modes, and restores from its tray. Ordinary use does not require a terminal.

For the source checkout, after installing pinned backend/desktop requirements and building `frontend/`:

```powershell
.\Start-Local-Runtime.ps1
.\Start-BEL.ps1
```

The source launcher reuses this checkout's `owner-data`. The installed application reuses an existing SIGHT OS data directory, otherwise `%LOCALAPPDATA%\BEL`. `BEL_DATA_DIR` or `--data-directory` can select existing data. The [versioned migration utility](sight/docs/BEL_MIGRATION.md) backs up data before recording BEL identity; memories, quota ledgers and legacy credentials are preserved.

## Current capabilities

- Supplied orb, authenticated HTTP/WebSockets, persistent conversation history, compact view, memory correction/deletion, provider settings, diagnostics and exact-action approval dialogs.
- Local Gemma reasoning, existing disabled-by-default Groq/Gemini/OpenRouter adapters, and optional ChatGPT compatibility. No paid services or quota resets are enabled by migration.
- Needle 3 proposes eligible registered calls. Schema, confidence and owner approval checks gate execution. Settings → Tools and undo provides manual review when routing declines.
- Verified private text-file creation/edit/rename with guarded undo. Application launch/focus is limited to trusted Notepad/Calculator identities and reports observed results.
- Existing local capabilities, durable jobs with 12 logical roles, declarative Forge validation/promotion/rollback, full-data backups and reviewed recovery.
- Windows speech-to-WAV and opt-in playback/stop. Optional offline Windows dictation places speech in an editable draft; it requires startup opt-in, session consent and hold-to-talk. Only installed languages are offered. Recognition can be inaccurate. A trained BEL wake detector remains unavailable.

The `/legacy/` interface and SIGHT launchers remain for compatibility. Historical pages, `sight_core`, database filenames, vault namespaces and protocol identifiers deliberately retain their names. New application identity is BEL. This migration did not rename the remote repository.

## Verify and build

```powershell
.\Verify-BEL.ps1
.\sight\scripts\build_windows.ps1 -OutputDirectory .\.cache\windows-release
```

The [setup guide](sight/docs/BEL_SETUP.md) covers pinned Needle provisioning, actual Windows verification, data paths and offline prerequisites. Builds use a fresh work directory and verify packaged Python code against source. Gemma weights, Chromium, private data and credentials are separate from Git. Microphone capture, auto-start, remote access and cloud inference remain opt-in or unavailable.

## Evidence and history

[Implementation report](sight/docs/BEL_IMPLEMENTATION.md) · [Migration and rollback](sight/docs/BEL_MIGRATION.md) · [Plan](PLAN.md) · [Publication](PUBLICATION.md)

The [27 October SIGHT audit](sight/docs/BROWSER_DIAGNOSTICS_20261027.md), [Phase 4 report](sight/docs/PHASE4_COMPLETION_20261024.md), and [22 October ZIP](dist/SIGHT-Phase4-Partial.zip) remain historical. The old `UPLOAD_MANIFEST.json` describes that earlier ZIP, not BEL. Arbitrary executable Forge skills, broader computer control, mobile pairing and autonomous self-modification are not claimed as working integrations.
