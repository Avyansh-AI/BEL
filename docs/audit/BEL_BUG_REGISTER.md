# BEL (Behavioral Executive Logic) — Comprehensive Bug Register

**Audit Date:** November 12, 2026  
**Auditor:** Senior Software Architect, QA & Security Auditor  
**Version:** 1.0.0 (Stage 10 V1 Golden Candidate)  
**Total Issues Cataloged:** 6 issues (0 Critical, 0 High, 2 Medium, 3 Low, 1 Informational)

---

## Severity Classification Scale
- **CRITICAL:** Security vulnerabilities, data corruption/loss, fundamental application crashes.
- **HIGH:** Major core functionality broken, non-operational, or unstable.
- **MEDIUM:** Important functionality partially working, gated by environmental friction, or missing automatic lifecycle management.
- **LOW:** Minor defects, deprecation warnings, path configuration friction, or developer experience inconsistencies.
- **INFORMATIONAL:** Architectural observations, branding artifacts, or optimization recommendations.

---

## Master Defect Register

### ISSUE-001 — Pytest Collection Recursing into Reference Repositories
- **Unique Issue ID:** `BUG-001`
- **Affected Feature:** Automated Test Runner & CI Infrastructure
- **File & Location:** Workspace root directory (`C:\Users\Dell\Documents\Ai projects\Sight`)
- **Severity:** **LOW**
- **Reproduction Steps:**
  1. Open terminal at workspace root (`C:\Users\Dell\Documents\Ai projects\Sight`).
  2. Execute `python -m pytest` without specifying test subdirectory.
- **Expected Behaviour:** Pytest should only discover tests within `github-publish/Sight/sight/tests/` and ignore reference repositories.
- **Actual Behaviour:** Pytest recurses into `references/repos/Brahma-AI/`, `references/repos/ada_v2/`, and `references/repos/hermes-agent/`, attempting to import dependencies not present in BEL's virtual environment, triggering collection errors.
- **Root Cause:** Absence of a workspace-root `pytest.ini` specifying explicit `testpaths` and `norecursedirs`.
- **Recommended Correction:** Add root-level `pytest.ini` with `testpaths = github-publish/Sight/sight/tests` and `norecursedirs = references Phase-1 Phase-2 Phase-3 Phase-4 dist .cache`.

---

### ISSUE-002 — Starlette TestClient Deprecation Warning
- **Unique Issue ID:** `BUG-002`
- **Affected Feature:** Test Suite Execution / API Client Testing
- **File & Location:** `github-publish\Sight\sight\.venv\Lib\site-packages\fastapi\testclient.py:1`
- **Severity:** **LOW**
- **Reproduction Steps:**
  1. Run any API test (e.g. `pytest tests/test_core.py`).
  2. Observe warnings summary.
- **Expected Behaviour:** Test run completes with 0 warnings.
- **Actual Behaviour:** Emits warning: `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`
- **Root Cause:** Upstream Starlette framework in FastAPI deprecates legacy httpx binding in testclient.
- **Recommended Correction:** Configure `filterwarnings = ["ignore::starlette.exceptions.StarletteDeprecationWarning"]` in `pyproject.toml` or update starlette testclient requirements.

---

### ISSUE-003 — Local Ollama Service Auto-Spawn Lifecycle Gap
- **Unique Issue ID:** `BUG-003`
- **Affected Feature:** Local Offline Model Inference (`sight_core/models.py`)
- **File & Location:** `github-publish\Sight\sight\sight_core\models.py:30-55`
- **Severity:** **MEDIUM**
- **Reproduction Steps:**
  1. Ensure local host Ollama service is stopped.
  2. Send a query configured for local offline inference.
- **Expected Behaviour:** If the local Ollama daemon on `127.0.0.1:11434` is unresponsive, BEL should automatically launch the cached portable Ollama binary (`.cache/preview2/ollama-0.40.9/ollama.exe`) as a supervised background subprocess.
- **Actual Behaviour:** `OllamaProvider` returns offline status or raises `ConnectionRefusedError`, requiring manual daemon launch by the user.
- **Root Cause:** `OllamaProvider` lacks an automatic startup daemon probe and process spawner for the bundled cached binary.
- **Recommended Correction:** Implement a lifecycle check in `models.py` or `runtime.py`: if port 11434 is unreachable, locate portable `ollama.exe` from cache and start it in background.

---

### ISSUE-004 — Creative Engine Path Discovery Limited to System PATH
- **Unique Issue ID:** `BUG-004`
- **Affected Feature:** Creative Development Agents (Blender, Godot, Unreal bridges)
- **File & Location:** `sight_core/blender_agent/blender_bridge.py:25`, `godot_bridge.py:20`, `unreal_bridge.py:20`
- **Severity:** **LOW**
- **Reproduction Steps:**
  1. Install Blender or Godot in standard Windows location (e.g. `C:\Program Files\Blender Foundation\Blender 4.2\blender.exe`).
  2. Do not add installation directory to system `PATH`.
  3. Query `/api/creative/blender/status`.
- **Expected Behaviour:** Bridge discovers installed application via standard Windows install paths or registry keys.
- **Actual Behaviour:** Status reports `installed: false` because `shutil.which("blender")` only checks `PATH`.
- **Root Cause:** Executable resolution relies solely on `PATH` environment variable without probing known standard Windows installation directories.
- **Recommended Correction:** Augment path resolution with a list of default Windows installation locations (`C:\Program Files\Blender Foundation\...`, `C:\Program Files\Epic Games\...`, etc.).

---

### ISSUE-005 — Manifest File Output Path Discrepancy in Golden Suite
- **Unique Issue ID:** `BUG-005`
- **Affected Feature:** Release Manifest Generator (`scripts/run_golden_suite.py`)
- **File & Location:** `github-publish\Sight\sight\scripts\run_golden_suite.py:103, 165`
- **Severity:** **INFORMATIONAL**
- **Reproduction Steps:**
  1. Run `python scripts/run_golden_suite.py`.
  2. Inspect output location of `BEL_V1_VALIDATION_MANIFEST.json`.
- **Expected Behaviour:** Manifest is written directly to the root workspace directory `C:\Users\Dell\Documents\Ai projects\Sight`.
- **Actual Behaviour:** Manifest is written to `github-publish/BEL_V1_VALIDATION_MANIFEST.json` because `repo_root = workspace_root.parents[1]`.
- **Root Cause:** Directory traversal `parents[1]` from `github-publish/Sight/sight/scripts` resolves to `github-publish/` rather than the top-level project workspace.
- **Recommended Correction:** Update `run_golden_suite.py` to write the manifest to both the active repository and the top-level project root directory.

---

### ISSUE-006 — Workspace Root Directory Name Legacy Artifact
- **Unique Issue ID:** `BUG-006`
- **Affected Feature:** Workspace Root Naming & Branding
- **File & Location:** `C:\Users\Dell\Documents\Ai projects\Sight`
- **Severity:** **INFORMATIONAL**
- **Reproduction Steps:**
  1. Inspect root directory name in filesystem.
- **Expected Behaviour:** Directory named `BEL`.
- **Actual Behaviour:** Directory named `Sight` due to project evolution history.
- **Root Cause:** Active IDE file locks held on open files prevent live atomic renaming of the root workspace directory while IDE sessions are running.
- **Recommended Correction:** Maintain documented 3-step manual rename guide for owner post-session.

---

## Defect Summary Table

| Issue ID | Severity | Feature | File & Location | Status |
| :---: | :---: | :--- | :--- | :---: |
| **BUG-001** | **LOW** | Test Infrastructure | Workspace root (`pytest.ini`) | **Ready for Repair** |
| **BUG-002** | **LOW** | TestClient Warning | `pyproject.toml` | **Ready for Repair** |
| **BUG-003** | **MEDIUM** | Local Ollama Lifecycle | `sight_core/models.py:30` | **Ready for Repair** |
| **BUG-004** | **LOW** | Creative Engine Discovery | `blender_bridge.py`, `godot_bridge.py` | **Ready for Repair** |
| **BUG-005** | **INFORMATIONAL** | Golden Suite Manifest | `scripts/run_golden_suite.py:165` | **Ready for Repair** |
| **BUG-006** | **INFORMATIONAL** | Workspace Root Folder | Root folder naming | **Documented** |

Phase 7 complete. Deliverable saved to `BEL_BUG_REGISTER.md`. Proceeding automatically to Phase 8 (Repair and Regression Testing).
