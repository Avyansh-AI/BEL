"""Unit tests for Stage 7 Unreal Engine Automation Agent."""
from __future__ import annotations

from pathlib import Path
import tempfile

from sight_core.unreal_agent import (
    UnrealAgent,
    UnrealScriptGenerator,
    UnrealScriptRequest,
)


def test_unreal_script_generator_templates():
    # 1. Spawn Actor
    spawn_code, desc = UnrealScriptGenerator.generate(
        task_type="spawn_actor",
        actor_class="StaticMeshActor",
        params={"x": 100.0, "y": 200.0, "z": 50.0, "label": "TestBox"},
    )
    assert "import unreal" in spawn_code
    assert "spawn_actor_from_class" in spawn_code
    assert "TestBox" in spawn_code
    assert "Vector(100.0, 200.0, 50.0)" in spawn_code

    # 2. Material Instance
    mat_code, _ = UnrealScriptGenerator.generate(
        task_type="create_material_instance",
        params={"name": "MI_CustomGlow", "folder": "/Game/Materials"},
    )
    assert "MaterialInstanceConstantFactoryNew" in mat_code
    assert "MI_CustomGlow" in mat_code

    # 3. Level Sequence
    seq_code, _ = UnrealScriptGenerator.generate(
        task_type="create_sequence",
        params={"name": "LS_IntroCinematic"},
    )
    assert "LevelSequenceFactoryNew" in seq_code
    assert "LS_IntroCinematic" in seq_code


def test_unreal_agent_script_export():
    with tempfile.TemporaryDirectory() as tmp_dir:
        agent = UnrealAgent(workspace_root=tmp_dir)
        status = agent.get_status()
        assert status is not None

        out_script = Path(tmp_dir) / "spawn_hero.py"
        req = UnrealScriptRequest(
            task_type="spawn_actor",
            actor_class="CineCameraActor",
            parameters={"label": "HeroCamera"},
            output_path=str(out_script),
        )
        res = agent.generate_script(req)
        assert res.task_type == "spawn_actor"
        assert out_script.exists()
        assert "HeroCamera" in out_script.read_text(encoding="utf-8")
