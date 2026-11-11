"""Data models for BEL Blender 3D Automation Agent (Stage 7)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class MaterialProperties(BaseModel):
    model_config = ConfigDict(extra="ignore")
    base_color: list[float] = Field(default_factory=lambda: [0.8, 0.8, 0.8, 1.0])
    metallic: float = 0.0
    roughness: float = 0.5
    specular: float = 0.5
    emission_color: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0, 1.0])
    emission_strength: float = 0.0


class BlenderStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    available: bool = False
    version: str | None = None
    executable_path: str | None = None
    fallback_mode: bool = True
    capabilities: list[str] = Field(default_factory=list)


class MeshRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mesh_type: str = "cube"
    parameters: dict = Field(default_factory=dict)
    material: MaterialProperties = Field(default_factory=MaterialProperties)
    output_format: str = "glb"  # glb, gltf, obj
    output_path: str | None = None


class MeshResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    success: bool = True
    file_path: str
    format: str
    vertex_count: int = 0
    face_count: int = 0
    generated_by: str = "blender_headless"
    error: str | None = None


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    mesh_type: str = "cube"
    parameters: dict = Field(default_factory=dict)
    material: MaterialProperties = Field(default_factory=MaterialProperties)
    resolution: list[int] = Field(default_factory=lambda: [800, 600])
    output_path: str | None = None
    samples: int = 64


class RenderResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    success: bool = True
    image_path: str
    resolution: list[int] = Field(default_factory=lambda: [800, 600])
    engine: str = "blender_cycles"
    duration_sec: float = 0.0
    error: str | None = None
