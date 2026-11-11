"""Data models for BEL Godot Game Development Agent (Stage 7)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GodotStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    available: bool = False
    version: str | None = None
    executable_path: str | None = None
    engine_version: str = "Godot 4.x"


class GodotProjectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    project_name: str
    target_dir: str
    renderer: str = "forward_plus"  # forward_plus, mobile, gl_compatibility


class GodotProjectInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    project_name: str
    project_path: str
    files_created: list[str] = Field(default_factory=list)
    main_scene: str = "res://scenes/main.tscn"


class GodotSceneRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    project_dir: str
    scene_name: str
    archetype: str = "2d_character"  # 2d_character, 3d_character, ui_menu, custom
    include_script: bool = True


class GodotSceneResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    scene_path: str
    script_path: str | None = None
    root_type: str
    nodes: list[str] = Field(default_factory=list)


class GodotInspectResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    project_name: str
    valid: bool = True
    scenes: list[str] = Field(default_factory=list)
    scripts: list[str] = Field(default_factory=list)
    godot_version: str = "4.x"
