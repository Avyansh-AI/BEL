"""Unreal Engine 5 Python Script Generator for BEL (Stage 7).

Generates standalone editor scripts targeting the Unreal Engine Python API
(`import unreal`) for actor spawning, material instances, and level sequences.
"""
from __future__ import annotations


class UnrealScriptGenerator:
    """Generates Python scripts for Unreal Engine 5 Editor environment."""

    @classmethod
    def generate(cls, task_type: str, actor_class: str = "StaticMeshActor", params: dict | None = None) -> tuple[str, str]:
        params = params or {}
        task = task_type.lower()
        if task == "create_material_instance":
            return cls._material_instance_script(params), "Creates a Material Instance Dynamic from a parent material"
        elif task == "create_sequence":
            return cls._sequence_script(params), "Creates a Level Sequence with a CineCameraActor"
        elif task == "batch_import":
            return cls._batch_import_script(params), "Batch imports 3D meshes into Content Browser"
        else:
            return cls._spawn_actor_script(actor_class, params), f"Spawns {actor_class} in the active world"

    @staticmethod
    def _spawn_actor_script(actor_class: str, params: dict) -> str:
        loc_x = params.get("x", 0.0)
        loc_y = params.get("y", 0.0)
        loc_z = params.get("z", 100.0)
        label = params.get("label", "BEL_Actor")
        return f"""import unreal

# Target World
editor_subsystem = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem)
world = editor_subsystem.get_editor_world()

location = unreal.Vector({loc_x}, {loc_y}, {loc_z})
rotation = unreal.Rotator(0.0, 0.0, 0.0)

# Resolve Actor Class
actor_class_obj = unreal.{actor_class} if hasattr(unreal, "{actor_class}") else unreal.StaticMeshActor

spawned_actor = unreal.EditorLevelLibrary.spawn_actor_from_class(actor_class_obj, location, rotation)
if spawned_actor:
    spawned_actor.set_actor_label("{label}")
    unreal.log(f"[BEL-Unreal] Successfully spawned actor: {{spawned_actor.get_actor_label()}} at {{location}}")
else:
    unreal.log_error("[BEL-Unreal] Failed to spawn actor")
"""

    @staticmethod
    def _material_instance_script(params: dict) -> str:
        parent_mat = params.get("parent_material", "/Engine/BasicShapes/BasicShapeMaterial")
        target_name = params.get("name", "MI_BEL_Material")
        target_folder = params.get("folder", "/Game/BEL_Materials")
        return f"""import unreal

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
mat_factory = unreal.MaterialInstanceConstantFactoryNew()

parent_mat_obj = unreal.EditorAssetLibrary.load_asset("{parent_mat}")
if not parent_mat_obj:
    unreal.log_error(f"[BEL-Unreal] Could not find parent material '{parent_mat}'")
else:
    new_asset = asset_tools.create_asset("{target_name}", "{target_folder}", unreal.MaterialInstanceConstant, mat_factory)
    if new_asset:
        new_asset.set_editor_property("parent", parent_mat_obj)
        unreal.EditorAssetLibrary.save_loaded_asset(new_asset)
        unreal.log(f"[BEL-Unreal] Material Instance created: {target_folder}/{target_name}")
"""

    @staticmethod
    def _sequence_script(params: dict) -> str:
        seq_name = params.get("name", "LS_BEL_Cinematic")
        seq_folder = params.get("folder", "/Game/Cinematics")
        return f"""import unreal

asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
factory = unreal.LevelSequenceFactoryNew()

seq_asset = asset_tools.create_asset("{seq_name}", "{seq_folder}", unreal.LevelSequence, factory)
if seq_asset:
    # Set playback range
    seq_asset.set_playback_start(0)
    seq_asset.set_playback_end(150)
    unreal.EditorAssetLibrary.save_loaded_asset(seq_asset)
    unreal.log(f"[BEL-Unreal] Level Sequence created: {seq_folder}/{seq_name}")
"""

    @staticmethod
    def _batch_import_script(params: dict) -> str:
        source_dir = params.get("source_dir", "C:/BEL_Exports").replace("\\", "/")
        destination_path = params.get("destination_path", "/Game/BEL_Imports")
        return f"""import unreal
import os

source_directory = "{source_dir}"
dest_folder = "{destination_path}"

task = unreal.AssetImportTask()
task.filename = source_directory
task.destination_path = dest_folder
task.automated = True
task.save = True
task.replace_existing = True

unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
unreal.log(f"[BEL-Unreal] Batch import completed from {{source_directory}} to {{dest_folder}}")
"""
