"""Data models for BEL Unreal Engine 5 Automation Agent (Stage 7)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class UnrealStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    available: bool = False
    remote_control_connected: bool = False
    engine_path: str | None = None
    engine_version: str | None = None


class UnrealScriptRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    task_type: str = "spawn_actor"  # spawn_actor, create_material_instance, create_sequence, batch_import
    actor_class: str = "StaticMeshActor"
    parameters: dict = Field(default_factory=dict)
    output_path: str | None = None


class UnrealScriptResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    script: str
    output_path: str | None = None
    task_type: str
    description: str


class UnrealRemoteCall(BaseModel):
    model_config = ConfigDict(extra="ignore")
    object_path: str
    function_name: str
    parameters: dict = Field(default_factory=dict)
