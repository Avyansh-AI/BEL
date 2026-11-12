"""Godot Game Development Bridge for BEL (Stage 7).

Provides Godot 4.x project scaffolding, scene graph generation,
GDScript creation, and project inspection.
"""
from __future__ import annotations

import glob
import os
from pathlib import Path
import shutil
import subprocess

from .gdscript_generator import GDScriptGenerator
from .models import (
    GodotInspectResult,
    GodotProjectInfo,
    GodotProjectRequest,
    GodotRunResult,
    GodotSceneRequest,
    GodotSceneResult,
    GodotStatus,
)
from .tscn_builder import TSCNBuilder


class GodotAgent:
    """Manages Godot 4.x engine projects, scenes, and script assets."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self._executable: Path | None = self._discover_godot()

    def _discover_godot(self) -> Path | None:
        # Check custom env
        env_path = os.environ.get("GODOT_BIN")
        if env_path and Path(env_path).exists():
            return Path(env_path)

        for name in ("godot", "godot4", "godot.exe", "godot4.exe"):
            which = shutil.which(name)
            if which:
                return Path(which)

        if os.name == "nt":
            standard_patterns = [
                r"C:\Program Files\Godot\*.exe",
                r"C:\Program Files (x86)\Godot\*.exe",
                r"C:\Godot\*.exe",
                r"C:\Godot4\*.exe",
            ]
            for pat in standard_patterns:
                candidates = glob.glob(pat)
                if candidates:
                    return Path(candidates[0])
        return None

    def get_status(self) -> GodotStatus:
        available = self._executable is not None and self._executable.exists()
        version = None
        if available:
            try:
                proc = subprocess.run(
                    [str(self._executable), "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                version = proc.stdout.strip()
            except Exception:
                version = "Installed (Version query failed)"

        return GodotStatus(
            available=available,
            version=version,
            executable_path=str(self._executable) if self._executable else None,
            engine_version="Godot 4.x",
        )

    def create_project(self, request: GodotProjectRequest) -> GodotProjectInfo:
        """Scaffold a full Godot 4.x project directory."""
        target_path = Path(request.target_dir)
        if not target_path.is_absolute():
            target_path = self.workspace_root / target_path

        target_path.mkdir(parents=True, exist_ok=True)
        (target_path / "scenes").mkdir(exist_ok=True)
        (target_path / "scripts").mkdir(exist_ok=True)
        (target_path / "assets").mkdir(exist_ok=True)

        files_created: list[str] = []

        # 1. project.godot
        project_godot = f"""; Engine configuration file.
; It's best edited using the editor UI and not directly,
; since the parameters that go here are not all obvious.
;
; Format:
;   [section] ; section goes between []
;   param=value ; assign values to parameters

config_version=5

[application]

config/name="{request.project_name}"
run/main_scene="res://scenes/main.tscn"
config/features=PackedStringArray("4.3", "Forward Plus")

[rendering]

renderer/rendering_method="{request.renderer}"
"""
        (target_path / "project.godot").write_text(project_godot, encoding="utf-8")
        files_created.append("project.godot")

        # 2. .gitignore
        gitignore = """.godot/
*.translation
"""
        (target_path / ".gitignore").write_text(gitignore, encoding="utf-8")
        files_created.append(".gitignore")

        # 3. Create default character script & scene
        script_code = GDScriptGenerator.generate_script("2d_character")
        (target_path / "scripts" / "player.gd").write_text(script_code, encoding="utf-8")
        files_created.append("scripts/player.gd")

        tscn_code, _, _ = TSCNBuilder.build_scene(
            archetype="2d_character",
            scene_name="Main",
            script_res_path="res://scripts/player.gd",
        )
        (target_path / "scenes" / "main.tscn").write_text(tscn_code, encoding="utf-8")
        files_created.append("scenes/main.tscn")

        return GodotProjectInfo(
            project_name=request.project_name,
            project_path=str(target_path),
            files_created=files_created,
            main_scene="res://scenes/main.tscn",
        )

    def create_scene(self, request: GodotSceneRequest) -> GodotSceneResult:
        """Create a new .tscn scene and optional GDScript in the project."""
        proj_dir = Path(request.project_dir)
        if not proj_dir.is_absolute():
            proj_dir = self.workspace_root / proj_dir

        if not proj_dir.exists():
            raise FileNotFoundError(f"Project directory does not exist: '{proj_dir}'")

        scenes_dir = proj_dir / "scenes"
        scripts_dir = proj_dir / "scripts"
        scenes_dir.mkdir(exist_ok=True)
        scripts_dir.mkdir(exist_ok=True)

        clean_name = request.scene_name.replace(" ", "_")
        script_path_str: str | None = None
        script_res: str | None = None

        if request.include_script:
            script_file = scripts_dir / f"{clean_name.lower()}.gd"
            script_content = GDScriptGenerator.generate_script(request.archetype)
            script_file.write_text(script_content, encoding="utf-8")
            script_path_str = str(script_file)
            script_res = f"res://scripts/{script_file.name}"

        tscn_content, root_type, nodes = TSCNBuilder.build_scene(
            archetype=request.archetype,
            scene_name=clean_name,
            script_res_path=script_res,
        )
        scene_file = scenes_dir / f"{clean_name.lower()}.tscn"
        scene_file.write_text(tscn_content, encoding="utf-8")

        return GodotSceneResult(
            scene_path=str(scene_file),
            script_path=script_path_str,
            root_type=root_type,
            nodes=nodes,
        )

    def inspect_project(self, project_dir: Path | str) -> GodotInspectResult:
        """Inspect a Godot project folder and return scenes and scripts."""
        proj_dir = Path(project_dir)
        if not proj_dir.is_absolute():
            proj_dir = self.workspace_root / proj_dir

        godot_file = proj_dir / "project.godot"
        if not godot_file.exists():
            return GodotInspectResult(
                project_name=proj_dir.name,
                valid=False,
                scenes=[],
                scripts=[],
                godot_version="unknown",
            )

        scenes = [str(p.relative_to(proj_dir)).replace("\\", "/") for p in proj_dir.rglob("*.tscn")]
        scripts = [str(p.relative_to(proj_dir)).replace("\\", "/") for p in proj_dir.rglob("*.gd")]

        return GodotInspectResult(
            project_name=proj_dir.name,
            valid=True,
            scenes=sorted(scenes),
            scripts=sorted(scripts),
            godot_version="4.x",
        )

    def run_project(
        self,
        project_dir: Path | str,
        headless: bool = True,
        timeout_sec: int = 15,
    ) -> GodotRunResult:
        """Execute a Godot 4.x project using the discovered Godot executable."""
        proj_dir = Path(project_dir)
        if not proj_dir.is_absolute():
            proj_dir = self.workspace_root / proj_dir

        if not (proj_dir / "project.godot").exists():
            return GodotRunResult(
                success=False,
                project_path=str(proj_dir),
                error=f"Invalid Godot project (missing project.godot): '{proj_dir}'",
            )

        if not self._executable or not self._executable.exists():
            return GodotRunResult(
                success=False,
                project_path=str(proj_dir),
                error="Godot 4 executable not found on host (set GODOT_BIN or install Godot 4).",
            )

        cmd = [str(self._executable), "--path", str(proj_dir)]
        if headless:
            cmd.extend(["--headless", "--quit"])

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            return GodotRunResult(
                success=proc.returncode == 0,
                project_path=str(proj_dir),
                exit_code=proc.returncode,
                stdout=proc.stdout[-4000:],
                stderr=proc.stderr[-4000:],
                error=None if proc.returncode == 0 else f"Godot exited with code {proc.returncode}",
            )
        except subprocess.TimeoutExpired as exc:
            return GodotRunResult(
                success=False,
                project_path=str(proj_dir),
                stdout=(exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
                error=f"Godot execution timed out after {timeout_sec}s",
            )
        except Exception as exc:
            return GodotRunResult(
                success=False,
                project_path=str(proj_dir),
                error=str(exc),
            )
