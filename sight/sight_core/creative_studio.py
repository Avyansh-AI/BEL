"""Stage 8: Complete Creative Development Module for BEL.

Unifies and extends BEL's BlenderAgent, GodotAgent, and UnrealAgent into
complete project creation, inspection, auto-correction, and packaging workflows.
"""
from __future__ import annotations

import json
from pathlib import Path
import zipfile
from typing import Any

from PIL import Image, ImageStat
from pydantic import BaseModel, ConfigDict, Field

from .blender_agent.blender_bridge import BlenderAgent
from .blender_agent.models import MaterialProperties, RenderRequest
from .godot_agent.godot_bridge import GodotAgent
from .godot_agent.models import GodotProjectRequest, GodotSceneRequest
from .unreal_agent.models import UnrealScriptRequest
from .unreal_agent.unreal_bridge import UnrealAgent


class RenderInspectionReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    image_path: str
    mean_brightness: float
    is_blank: bool
    passed: bool
    auto_corrected: bool = False
    attempts: int = 1


class GodotDeliveryReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    project_path: str
    valid: bool
    issues_fixed: list[str] = Field(default_factory=list)
    executed: bool = False
    package_path: str | None = None


class UnrealProjectReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    project_path: str
    uproject_file: str
    cpp_files: list[str] = Field(default_factory=list)
    editor_scripts: list[str] = Field(default_factory=list)
    engine_available: bool = False


class CreativeStudio:
    """Complete creative workflow orchestrator across Blender, Godot 4, and UE5."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.blender = BlenderAgent(self.workspace_root / "blender")
        self.godot = GodotAgent(self.workspace_root / "godot")
        self.unreal = UnrealAgent(self.workspace_root / "unreal")

    def inspect_render(self, image_path: Path | str, *, min_brightness: float = 5.0) -> tuple[float, bool]:
        with Image.open(image_path) as img:
            gray = img.convert("L")
            stat = ImageStat.Stat(gray)
            mean_b = float(stat.mean[0])
            stddev = float(stat.stddev[0])
            is_blank = stddev < 0.5 and mean_b < min_brightness
            return round(mean_b, 2), is_blank

    def blender_create_and_inspect(
        self,
        mesh_type: str = "cube",
        *,
        base_color: tuple[float, float, float, float] = (0.05, 0.05, 0.05, 1.0),
    ) -> RenderInspectionReport:
        """Render a 3D asset, visually inspect brightness/blankness, and auto-correct if too dark."""
        req = RenderRequest(
            mesh_type=mesh_type,
            resolution=(160, 120),
            samples=4,
            material=MaterialProperties(base_color=base_color),
        )
        res = self.blender.render_mesh(req)
        mean_b, is_blank = self.inspect_render(res.image_path)
        auto_corrected = False
        attempts = 1

        if is_blank or mean_b < 20.0:
            # Automatic render correction: brighten albedo and re-render
            corrected_req = RenderRequest(
                mesh_type=mesh_type,
                resolution=(160, 120),
                samples=4,
                material=MaterialProperties(base_color=(0.75, 0.85, 0.95, 1.0)),
            )
            res = self.blender.render_mesh(corrected_req)
            mean_b, is_blank = self.inspect_render(res.image_path)
            auto_corrected = True
            attempts = 2

        return RenderInspectionReport(
            image_path=res.image_path,
            mean_brightness=mean_b,
            is_blank=is_blank,
            passed=not is_blank,
            auto_corrected=auto_corrected,
            attempts=attempts,
        )

    @staticmethod
    def generate_blender_animation_script(object_name: str = "Cube", frames: int = 60) -> str:
        return (
            "import bpy\n"
            f"obj = bpy.data.objects.get('{object_name}')\n"
            "if obj:\n"
            "    obj.location = (0.0, 0.0, 0.0)\n"
            "    obj.keyframe_insert(data_path='location', frame=1)\n"
            "    obj.location = (2.0, 0.0, 1.0)\n"
            f"    obj.keyframe_insert(data_path='location', frame={frames})\n"
        )

    def godot_create_and_package(self, project_name: str) -> GodotDeliveryReport:
        """Scaffold a Godot 4 project, validate scripts, run if available, and package."""
        proj_dir = self.workspace_root / "godot" / project_name
        self.godot.create_project(GodotProjectRequest(project_name=project_name, target_dir=str(proj_dir)))
        self.godot.create_scene(GodotSceneRequest(project_dir=str(proj_dir), scene_name="Level1", archetype="2d_character"))

        issues_fixed: list[str] = []
        for gd_file in proj_dir.rglob("*.gd"):
            text = gd_file.read_text(encoding="utf-8")
            if not text.lstrip().startswith("extends "):
                gd_file.write_text("extends Node\n" + text, encoding="utf-8")
                issues_fixed.append(f"Added missing extends header to {gd_file.name}")

        insp = self.godot.inspect_project(proj_dir)
        executed = False
        if self.godot.get_status().available:
            run_res = self.godot.run_project(proj_dir, headless=True, timeout_sec=10)
            executed = run_res.success

        pkg_path = self.workspace_root / "godot" / f"{project_name}.zip"
        with zipfile.ZipFile(pkg_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in proj_dir.rglob("*"):
                if p.is_file():
                    zf.write(p, arcname=str(p.relative_to(proj_dir)).replace("\\", "/"))

        return GodotDeliveryReport(
            project_path=str(proj_dir),
            valid=insp.valid,
            issues_fixed=issues_fixed,
            executed=executed,
            package_path=str(pkg_path),
        )

    def unreal_scaffold_project(self, project_name: str) -> UnrealProjectReport:
        """Generate a UE5 .uproject, C++ module files, and Editor Python automation script."""
        proj_dir = self.workspace_root / "unreal" / project_name
        source_dir = proj_dir / "Source" / project_name
        source_dir.mkdir(parents=True, exist_ok=True)

        uproject = {
            "FileVersion": 3,
            "EngineAssociation": "5.4",
            "Category": "",
            "Description": "Generated by BEL CreativeStudio",
            "Modules": [{"Name": project_name, "Type": "Runtime", "LoadingPhase": "Default"}],
        }
        uproj_path = proj_dir / f"{project_name}.uproject"
        uproj_path.write_text(json.dumps(uproject, indent=2), encoding="utf-8")

        header_path = source_dir / f"{project_name}Actor.h"
        header_path.write_text(
            f"#pragma once\n#include \"CoreMinimal.h\"\n#include \"GameFramework/Actor.h\"\n"
            f"UCLASS()\nclass A{project_name}Actor : public AActor {{ GENERATED_BODY() }};\n",
            encoding="utf-8",
        )
        script_res = self.unreal.generate_script(
            UnrealScriptRequest(
                task_type="spawn_actor",
                actor_class="StaticMeshActor",
                output_path=str(proj_dir / "Scripts" / "setup_level.py"),
            )
        )

        return UnrealProjectReport(
            project_path=str(proj_dir),
            uproject_file=str(uproj_path),
            cpp_files=[str(header_path)],
            editor_scripts=[script_res.output_path] if script_res.output_path else [],
            engine_available=self.unreal.get_status().available,
        )
