"""Unit tests for Stage 7 Blender 3D Automation Agent."""
from __future__ import annotations

import io
from pathlib import Path
import struct
import tempfile
from PIL import Image

from sight_core.blender_agent import (
    BlenderAgent,
    MaterialProperties,
    MeshGenerator,
    MeshRequest,
    RenderRequest,
)


def test_procedural_mesh_primitives():
    # Test Cube
    cube = MeshGenerator.create_cube(size=2.0)
    assert cube.vertex_count == 24
    assert cube.face_count == 12

    # Test Sphere
    sphere = MeshGenerator.create_sphere(radius=1.0, rings=8, sectors=12)
    assert sphere.vertex_count > 50
    assert sphere.face_count > 50

    # Test Cylinder
    cyl = MeshGenerator.create_cylinder(radius=1.0, height=2.0, segments=16)
    assert cyl.vertex_count == 32
    assert cyl.face_count == 32


def test_procedural_mesh_obj_export():
    cube = MeshGenerator.create_cube(size=2.0)
    obj_str = cube.to_obj()

    assert "o Cube" in obj_str
    assert "v " in obj_str
    assert "vn " in obj_str
    assert "f " in obj_str


def test_procedural_mesh_glb_export_spec():
    cube = MeshGenerator.create_cube(size=2.0)
    glb_bytes = cube.to_glb()

    # GLB binary specification header:
    # 4 bytes: Magic (0x46546C67 -> b"glTF")
    # 4 bytes: Version (2)
    # 4 bytes: Total length
    assert len(glb_bytes) >= 20
    magic, version, total_len = struct.unpack_from("<4sII", glb_bytes, 0)
    assert magic == b"glTF"
    assert version == 2
    assert total_len == len(glb_bytes)

    # First chunk must be JSON chunk (0x4E4F534A)
    chunk0_len, chunk0_type = struct.unpack_from("<II", glb_bytes, 12)
    assert chunk0_type == 0x4E4F534A
    json_bytes = glb_bytes[20 : 20 + chunk0_len]
    assert b"\"asset\"" in json_bytes
    assert b"\"version\":\"2.0\"" in json_bytes


def test_procedural_mesh_software_preview_render():
    cube = MeshGenerator.create_cube(size=2.0)
    img = cube.render_preview(width=400, height=300)

    assert isinstance(img, Image.Image)
    assert img.size == (400, 300)
    assert img.mode == "RGBA"


def test_blender_agent_fallback_generation():
    with tempfile.TemporaryDirectory() as tmp_dir:
        agent = BlenderAgent(workspace_root=tmp_dir)
        status = agent.get_status()

        assert status is not None
        assert "procedural_3d_mesh_synthesis" in status.capabilities

        # Generate GLB mesh
        out_glb = Path(tmp_dir) / "model.glb"
        req = MeshRequest(
            mesh_type="sphere",
            output_format="glb",
            output_path=str(out_glb),
        )
        res = agent.generate_mesh(req)
        assert res.success is True
        assert out_glb.exists()
        assert out_glb.stat().st_size > 100

        # Generate OBJ mesh
        out_obj = Path(tmp_dir) / "model.obj"
        req_obj = MeshRequest(
            mesh_type="cube",
            output_format="obj",
            output_path=str(out_obj),
        )
        res_obj = agent.generate_mesh(req_obj)
        assert res_obj.success is True
        assert out_obj.exists()
        assert "v " in out_obj.read_text(encoding="utf-8")

        # Generate render preview
        out_img = Path(tmp_dir) / "preview.png"
        render_req = RenderRequest(
            mesh_type="cube",
            resolution=[320, 240],
            output_path=str(out_img),
        )
        render_res = agent.render_mesh(render_req)
        assert render_res.success is True
        assert out_img.exists()
        with Image.open(out_img) as opened:
            assert opened.size == (320, 240)
