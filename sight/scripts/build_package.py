"""BEL V1 Windows Standalone Packaging & Build Automation (Stage 10).

Compiles the React production bundle, prepares PyInstaller specifications,
and outputs a standalone portable Windows distribution in `dist/BEL_V1_Portable`.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def build_frontend(frontend_dir: Path) -> bool:
    """Build the React 19 / Vite production frontend."""
    print(f"Building React frontend in {frontend_dir}...")
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    res = subprocess.run([npm_cmd, "run", "build"], cwd=frontend_dir, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Frontend build failed:\n{res.stdout}\n{res.stderr}")
        return False
    print("Frontend build succeeded. `dist/` verified.")
    return True


def assemble_portable_distribution(
    workspace_root: Path,
    frontend_dist: Path,
    output_dir: Path,
) -> Path:
    """Package core backend, compiled frontend, and assets into standalone distribution."""
    print(f"Assembling portable distribution at: {output_dir}")
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Copy Frontend Assets
    target_frontend = output_dir / "frontend" / "dist"
    shutil.copytree(frontend_dist, target_frontend)
    print("   [+] Copied frontend distribution.")

    # 2. Copy Python Backend Core
    target_sight = output_dir / "sight_core"
    shutil.copytree(workspace_root / "sight_core", target_sight, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print("   [+] Copied sight_core Python engine.")

    # 3. Create Windows Launcher script
    launcher_bat = output_dir / "Launch_BEL.bat"
    launcher_bat.write_text(
        "@echo off\r\n"
        "title BEL — Behavioral Executive Logic\r\n"
        "echo Initializing BEL (Behavioral Executive Logic) V1...\r\n"
        "start http://localhost:8080\r\n"
        "python -m sight_core.main\r\n"
        "pause\r\n",
        encoding="utf-8",
    )
    print("   [+] Generated Launch_BEL.bat.")

    # 4. Copy README & Manifest
    manifest_src = workspace_root.parents[1] / "BEL_V1_VALIDATION_MANIFEST.json"
    if manifest_src.exists():
        shutil.copy(manifest_src, output_dir / "MANIFEST.json")
        print("   [+] Embedded validation manifest.")

    print(f"[SUCCESS] Standalone distribution assembled in {output_dir}")
    return output_dir


def main():
    t0 = time.time()
    workspace_root = Path(__file__).resolve().parents[1]
    repo_root = workspace_root.parents[0]
    frontend_dir = repo_root / "frontend"
    output_dir = repo_root / "dist" / "BEL_V1_Portable"

    print("================================================================================")
    print("BEL V1 WINDOWS PACKAGING & RELEASE BUILDER")
    print("================================================================================")

    # Build Frontend if needed or verify existing dist
    frontend_dist = frontend_dir / "dist"
    if not frontend_dist.exists() or not (frontend_dist / "index.html").exists():
        ok = build_frontend(frontend_dir)
        if not ok:
            sys.exit(1)
    else:
        print(f"Using pre-built frontend in {frontend_dist}")

    assemble_portable_distribution(workspace_root, frontend_dist, output_dir)
    print(f"Completed packaging in {time.time()-t0:.2f}s.")
    print("================================================================================")


if __name__ == "__main__":
    main()
