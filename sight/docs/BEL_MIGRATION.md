# BEL migration inventory and checklist — 27 October 2026

BEL means **Behavioral Executive Logic**. This migration uses the supplied React interface and the existing Python backend. The owner reconfirmed `gemma4:e4b-it-qat` with the verified thinking profile as the main model. Needle 3 has a separate tool-proposal role. No remote repository rename is requested or planned.

## Verified rollback point

The pre-migration source is commit `b859f5690e97e584975e0a5d17d6bca5aa190dd3`, local tag `rollback/sight-verified-20261027`. It incorporates the prior audit repairs over published commit `372df995004bf640f352e06c8ea25c942b468663`.

Baseline evidence: **379 regressions, 57/57 live application checks, 30/30 browser captures, 16 unchanged UI comparisons**, and **487/487 checks over 3,605.031 seconds** with real Gemma, three crash/restarts, six browser captures and full data restoration. See [baseline report](BROWSER_DIAGNOSTICS_20261027.md). These results do not qualify subsequent BEL changes.

A verified Git bundle exists outside the checkout at `../../rollback-baselines/20261027-b859f56/SIGHT-baseline.bundle`, SHA-256 `49e7a29ebc705b302bb9fbff2132e16dadb494a1c836180e162c5afcc810ec1c`. The current checkout's owner directory contains only `local-model.json`; it was copied and hash-verified separately. Earlier phase databases and memories remain in their original locations. No owner database was created merely to claim a backup.

The baseline publication scan checked 821 staged files against 11 supplied credentials with zero matches. Its first path-policy check incorrectly flagged byte-identical, already-published historical test evidence; a narrowly scoped original-blob check corrected that classifier, and the final staged-byte verification passed. Original diagnostic logs retain whitespace rather than being rewritten; source/document whitespace checks pass. No remote push has occurred for this baseline.

## Detected architecture

| Component | Existing implementation and migration boundary |
| --- | --- |
| `sight/sight_core/` | Python 3.12 FastAPI backend, provider routing, schemas, auth, memory, jobs, Forge, tools and recovery. Keep the internal package initially for compatibility. |
| `sight/apps/ui/` | Six static HTML/JavaScript pages. Preserve them as legacy assets and rollback evidence; replace the primary route with the selected React interface. |
| Supplied React source | `C:/Users/Dell/Documents/bel-interface-source.zip`, SHA-256 `6bd225168ee757fea15fd25ba8b36b46671fc7af1f606a7958673aed619b22c7`. Safely extracted separately; 27 entries, 497,794 expanded bytes. React 18, TypeScript 5, Vite 6, Framer Motion and supplied CSS orb. |
| Authentication | HttpOnly `sight_session`, CSRF header, exact action grants and one-use WebSocket tickets. Serve React from the same loopback origin; retain protocol compatibility. |
| Data | `sight.sqlite3` schema 1 and `brain.sqlite3` schema 2; persistent retrieval, provenance, privacy, correction/deletion, quotas, tasks and receipts. Retain filenames, data and backup format. |
| Credentials | OS keyring service `SIGHT`; ChatGPT vault also depends on data-directory identity. Default to in-place data reuse; copied migration must explain any reauthorization. |
| Models | Verified Ollama Gemma and existing disabled-by-default cloud providers. Keep spending/quota policies. Needle must propose registered calls, never execute its own functions. |
| Tools/jobs | Typed local capabilities and approvals, fixed workers, durable sequential DAG runner with 12 logical roles. Add verified outcomes, execution receipts, bounded routing and supported undo incrementally. |
| Voice | Actual local Windows speech-to-WAV only. Microphone, local STT, playback, interruption and trained BEL wake detection are additional work; no trained BEL model is supplied. |
| Desktop | No desktop shell/tray/EXE framework exists. PowerShell currently starts Python and the system browser. Frozen packaging must replace `sys.executable -m/-I` child dispatch with fixed executable modes. |
| Forge/recovery | Restricted declarative skills, explicit promotion, immutable versions, tests and rollback; full-data recovery and selected code snapshots. Arbitrary generated executable skills remain a separate secured subsystem. |

The supplied UI currently contains simulated offline responses, an unauthenticated transport, browser-dependent speech recognition, remote font loading and a 30-second request timeout. Those behaviors must be replaced or explicitly disabled while preserving its orb, colors, layout and animations. Its history/settings/compact components can be reused. It contains no native desktop host or Python service.

## Dependency-ordered implementation

1. Centralize BEL identity and refined professional personality; add `BEL_*` configuration aliases and a versioned, idempotent migration with verified backups. Preserve compatibility identifiers and user-authored text.
2. Integrate the supplied React source, real session/CSRF/WebSocket flow, bounded persistent conversation history, settings, memory and human approval dialogs. Remove demo replies and synthetic speech claims.
3. Add a Windows desktop shell, active/compact/background modes, tray lifecycle and fixed packaged worker dispatch. Build and exercise `BEL.exe` where the installed Windows runtime permits it.
4. Extend the existing tool registry with output/permission/risk/version/deadline/reversibility metadata. Add a bounded proposal-only Needle 3 worker, validation, safe fallback, execution receipts and duplicate/cancellation budgets.
5. Add verified outcomes and scoped undo/app identity operations. Preserve exact human authority; model parameters cannot grant approval.
6. Add opt-in local speech/device handling and a valid-model-only BEL wake integration path. No sleeping audio leaves the machine; no microphone or auto-start is enabled by migration.
7. Extend monitoring, paired remote control and isolated Forge development only after the above works. Keep unavailable or experimental capabilities explicit.
8. Run regression and real integration checks per phase, verify the Windows artifact, record limitations, then update GitHub under the owner's authorization. Do not label missing hardware/model validation as a pass.

## Rollback procedure

Use a separate checkout of `rollback/sight-verified-20261027` or restore from the verified Git bundle; do not reset over uncommitted BEL work. The source rollback does not restore or delete owner memories. Data rollback uses the separately verified backup into a new directory, preserving the original. The old SIGHT launchers and data formats remain available during migration.

For implemented changes, test evidence and current limitations, read the [BEL implementation report](BEL_IMPLEMENTATION.md). For operating and migration commands, read the [setup guide](BEL_SETUP.md).
