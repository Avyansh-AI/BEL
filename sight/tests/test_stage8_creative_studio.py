"""Stage 8 Verification Tests: Complete Creative Development Module."""
from pathlib import Path
from sight_core.creative_studio import CreativeStudio


def test_stage8_blender_godot_unreal_workflows(tmp_path):
    studio = CreativeStudio(tmp_path)

    # 1. Blender render + visual inspection + auto-correction
    b_rep = studio.blender_create_and_inspect("cube", base_color=(0.01, 0.01, 0.01, 1.0))
    assert b_rep.passed and Path(b_rep.image_path).exists()
    anim = studio.generate_blender_animation_script("Cube", frames=30)
    assert "keyframe_insert" in anim

    # 2. Godot 4 full project + script check + packaging
    g_rep = studio.godot_create_and_package("SpaceDemo")
    assert g_rep.valid and g_rep.package_path and Path(g_rep.package_path).exists()

    # 3. Unreal Engine 5 project + C++ + Editor Python scaffolding
    u_rep = studio.unreal_scaffold_project("BelArena")
    assert Path(u_rep.uproject_file).exists()
    assert len(u_rep.cpp_files) == 1 and Path(u_rep.cpp_files[0]).exists()
    assert len(u_rep.editor_scripts) == 1 and Path(u_rep.editor_scripts[0]).exists()
