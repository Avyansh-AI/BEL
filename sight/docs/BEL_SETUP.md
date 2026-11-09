# BEL setup and operation

BEL continues the SIGHT Python backend with the owner's supplied React orb interface. This is a **PARTIAL** release. Read [migration and rollback](BEL_MIGRATION.md) and [implementation evidence](BEL_IMPLEMENTATION.md) before relying on an optional integration.

## Windows application

Keep `BEL.exe`, `BEL-worker.exe` and `_internal` together in the verified release directory. Open `BEL.exe`; ordinary use does not require a terminal. The desktop needs Microsoft Edge WebView2. It binds only to loopback and opens its own authenticated window. Use its menu to switch between active, compact and background modes; the tray restores the window or quits the application. Closing the main window hides it only when the tray is available. Background mode keeps the backend running; a trained BEL wake listener is not yet available.

The installed application stores data in `%LOCALAPPDATA%\BEL`, or reuses an existing `%LOCALAPPDATA%\SIGHT` directory to preserve credentials and memory. `BEL_DATA_DIR` takes priority over the legacy `SIGHT_DATA_DIR`. To explicitly use this checkout's existing data, run:

```powershell
.\BEL.exe --data-directory 'C:\path\to\Sight\owner-data'
```

Do not run two instances against the same directory. Logs are bounded in that data directory as `desktop.log`. Existing saved model settings win over defaults. A fresh desktop profile selects the owner-approved `gemma4:e4b-it-qat` with thinking enabled, but does not download it or start Ollama. Run the existing [local runtime helper](../../Start-Local-Runtime.ps1) or start Ollama separately. A missing model produces an unavailable state; built-in help and local tools remain usable.

Auto-start is off by default. To opt in, run `BEL.exe --enable-autostart`; to remove BEL's own startup entry, run `BEL.exe --disable-autostart`. This changes only the current user's BEL Run entry. Microphone capture, cloud inference and remote listening are not enabled by installation or auto-start.

## Build from source

Use Windows x64, Python 3.12 and Node with npm. From the checkout:

```powershell
.\sight\scripts\install.ps1
.\sight\.venv\Scripts\python.exe -m pip install --only-binary=:all: --require-hashes -r .\sight\requirements-desktop.lock
Push-Location frontend
npm ci
npm test
npm run build
Pop-Location
.\sight\.venv\Scripts\python.exe .\sight\scripts\provision_needle.py --destination .\.cache\needle3
.\Start-Local-Runtime.ps1
.\Start-BEL.ps1
```

The source launcher uses `pythonw.exe`, hides the console, and reuses the checkout's `owner-data` unless an explicit or environment directory is supplied. Earlier SIGHT launchers and `/legacy/` pages remain available for compatibility. `Start-SIGHT.ps1` still runs the headless backend; its root route now serves the built BEL frontend.

To build the application after tests:

```powershell
.\sight\scripts\build_windows.ps1 -OutputDirectory .\.cache\windows-release
.\sight\.venv\Scripts\python.exe .\sight\scripts\verify_windows_release.py --executable .\.cache\windows-release\BEL\BEL.exe --output .\.cache\windows-release\verification.json --needle-assets .\.cache\windows-release\BEL\_internal\models\needle3
```

Each build uses a fresh PyInstaller work directory, rejects source changes during packaging, compares packaged Python code with source, and produces a SHA-256 manifest. The archive is unsigned. Windows fresh-account installation remains a separate verification gate. The build requires the pinned, verified Needle assets and packages them with their Apache-2.0 license. Gemma weights and the Playwright Chromium cache remain separate; browser tools report a missing prerequisite if the matching browser is absent. The existing installer provisions Chromium explicitly. Neither the EXE nor a tool request downloads a browser silently.

## Memory and migration

Stop the application before migration or full backup. The migration runs **in place** and first creates a verified sibling backup; it does not move, erase, rename or recreate memories:

```powershell
Push-Location sight
.\.venv\Scripts\python.exe -m sight_core.cli migrate --data-directory 'C:\path\to\owner-data'
Pop-Location
```

The versioned `bel-migration.json` marker is idempotent. Legacy database filenames, keyring namespaces, cookie/header names and environment aliases remain intentional compatibility identifiers. No remote repository rename is performed. Saved facts and projects remain distinct from the capped conversation journal. Clear History removes the journal only; memory correction/deletion uses the Memory panel. Existing backups retain earlier data until the owner removes them.

Full backups and restoration use `python -m sight_core.cli backup-all <new-backup-directory>` and `restore-all <backup-directory> <new-data-directory>` with `BEL_DATA_DIR` set appropriately. Inspect restoration before launching it. Undo journals copied to a different data directory are marked unverified: inode-dependent operations must not be replayed against restored files.

## Tools and voice

Needle proposes eligible calls; schema validation and a one-use, session-bound owner approval gate execution. Settings → Tools and undo offers manual reviewed tools when routing declines. The dialog names a reversal's target. File create/edit/rename undo is limited to BEL's private text workspace and refuses files changed outside the recorded action. Application launch supports only Notepad and Calculator with trusted process/window verification. No unrestricted shell, arbitrary paths or automatic model tool loops are exposed.

Reviewed Windows speech rendering creates a WAV; the interface can play it and stop playback. Preview 2 (0.4.2.dev2) adds a separately installed CPU whisper.cpp recognizer alongside selectable Windows dictation. It stays off on ordinary startup. To offer it, launch with `BEL.exe --local-dictation`, use `Start-BEL.ps1 -LocalDictation`, or explicitly set `BEL_LOCAL_STT=windows` or `whisper_cpp`. `disabled` is the default; invalid values fail startup. The legacy `SIGHT_LOCAL_STT` alias remains supported, with an explicit BEL value taking priority. See [offline speech setup](BEL_OFFLINE_SPEECH.md) for pinned models, explicit installation and local fallback controls. This does not change the selected Gemma model.

In Settings, enable **Microphone consent** for the current session, choose an available engine/language, then hold **Hold to talk**. Windows/WebView2 separately grants microphone permission; device choices appear after a successful grant. Release to transcribe at most 20 seconds locally. BEL displays a separate editable speech draft. **Send reviewed message** explicitly combines it with any typed text; **Discard speech draft** preserves typed text. Recognition never triggers chat or tools by itself. Windows has an installed en-US recognizer on the development machine. Multilingual Whisper offers Hindi/automatic language detection, whose measured limitations are separate from English and physical microphone acceptance.

Mute revokes session consent and cancels pending recognition. Discard Transcript stops the named request; changing devices/language or hiding the page discards pending audio. Permission loss stops capture. Raw recordings and unsent transcripts are not saved by the backend. Normal message/history policies apply only after you explicitly Send. Each owner session accepts at most 512 unique dictation request IDs; reopening BEL creates a new session if that limit is reached. This prevents a delayed or replayed cancelled request from restarting recognition.

The preview has simulated-device browser checks and actual local recognition evidence; these do not qualify physical microphones or native permission prompts. No trained BEL wake model is available. Browser cloud speech recognition is not used. Background mode keeps the backend manageable but does not listen for a wake word. See the [Preview 2 report](BEL_PREVIEW2_REPORT.md) and [owner hardware checklist](BEL_VOICE_HARDWARE.md) for exact acceptance and remaining gates. The [Preview 1 report](BEL_DICTATION_PREVIEW.md) remains historical.

Cloud policies and their rolling free-tier ledgers are retained. Services stay disabled until explicitly configured; paid use is not authorized. The optional ChatGPT adapter and advanced legacy interfaces remain separate from the three free-provider settings cards. No cloud inference is part of this release's acceptance evidence.

## Forge and production separation

Current Forge creates and validates restricted declarative text transformations with explicit promotion, immutable versions and rollback. It does not generate unrestricted executable skills. The packaged installation, writable source checkout, private data, skill storage and verified release backups have separate roles. Changes to core code belong in a disposable source checkout and require tests and approval before deployment; the running EXE does not patch itself.
