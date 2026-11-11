"""Unit tests for Stage 7 Godot Game Development Agent."""
from __future__ import annotations

from pathlib import Path
import tempfile

from sight_core.godot_agent import (
    GDScriptGenerator,
    GodotAgent,
    GodotProjectRequest,
    GodotSceneRequest,
    TSCNBuilder,
)


def test_tscn_builder_archetypes():
    # 2D Character Archetype
    tscn_2d, root_type_2d, nodes_2d = TSCNBuilder.build_scene(
        archetype="2d_character",
        scene_name="Hero",
        script_res_path="res://scripts/hero.gd",
    )
    assert root_type_2d == "CharacterBody2D"
    assert "CollisionShape2D" in nodes_2d
    assert "Sprite2D" in nodes_2d
    assert "Camera2D" in nodes_2d
    assert 'uid="uid://' in tscn_2d
    assert 'res://scripts/hero.gd' in tscn_2d

    parsed_nodes_2d = TSCNBuilder.parse_nodes(tscn_2d)
    assert len(parsed_nodes_2d) == 4

    # 3D Character Archetype
    tscn_3d, root_type_3d, nodes_3d = TSCNBuilder.build_scene(
        archetype="3d_character",
        scene_name="Player3D",
    )
    assert root_type_3d == "CharacterBody3D"
    assert "MeshInstance3D" in nodes_3d

    # UI Menu Archetype
    tscn_ui, root_type_ui, nodes_ui = TSCNBuilder.build_scene(
        archetype="ui_menu",
        scene_name="MainMenu",
    )
    assert root_type_ui == "Control"
    assert "StartButton" in nodes_ui
    assert "QuitButton" in nodes_ui


def test_gdscript_generator_and_validator():
    script_2d = GDScriptGenerator.generate_script("2d_character")
    assert "extends CharacterBody2D" in script_2d
    assert "move_and_slide()" in script_2d

    # Validation should pass on generated code
    valid, err = GDScriptGenerator.validate_syntax(script_2d)
    assert valid is True
    assert err is None

    # Missing extends
    invalid_script1 = "func test():\n    pass\n"
    valid1, err1 = GDScriptGenerator.validate_syntax(invalid_script1)
    assert valid1 is False
    assert "Missing 'extends" in err1

    # Missing trailing colon
    invalid_script2 = "extends Node\nfunc broken()\n    pass\n"
    valid2, err2 = GDScriptGenerator.validate_syntax(invalid_script2)
    assert valid2 is False
    assert "Missing trailing colon" in err2


def test_godot_agent_project_lifecycle():
    with tempfile.TemporaryDirectory() as tmp_dir:
        agent = GodotAgent(workspace_root=tmp_dir)

        # 1. Project Scaffolding
        proj_req = GodotProjectRequest(
            project_name="StarQuest",
            target_dir=str(Path(tmp_dir) / "StarQuest"),
            renderer="forward_plus",
        )
        info = agent.create_project(proj_req)
        assert info.project_name == "StarQuest"
        assert "project.godot" in info.files_created
        assert "scenes/main.tscn" in info.files_created
        assert "scripts/player.gd" in info.files_created

        # 2. Inspect Project
        inspect_res = agent.inspect_project(info.project_path)
        assert inspect_res.valid is True
        assert len(inspect_res.scenes) >= 1
        assert len(inspect_res.scripts) >= 1

        # 3. Create Additional Scene
        scene_req = GodotSceneRequest(
            project_dir=info.project_path,
            scene_name="EnemyMob",
            archetype="2d_character",
            include_script=True,
        )
        scene_res = agent.create_scene(scene_req)
        assert scene_res.root_type == "CharacterBody2D"
        assert Path(scene_res.scene_path).exists()
        assert Path(scene_res.script_path).exists()

        # 4. Re-inspect
        re_inspect = agent.inspect_project(info.project_path)
        assert len(re_inspect.scenes) == 2
        assert len(re_inspect.scripts) == 2
