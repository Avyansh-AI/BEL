"""Integration tests for Stage 7 Coding & Creative Intelligence REST Endpoints."""
from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from sight_core.api import create_app
from sight_core.config import Config

URL = "http://127.0.0.1:8080"


def authenticate(client, app):
    client.post(
        "/api/session/claim",
        json={"token": app.state.bootstrap_token},
        headers={"origin": URL},
    ).raise_for_status()
    client.headers["x-sight-csrf"] = client.get("/api/session").json()["csrf"]


@pytest.fixture
def api_client(tmp_path):
    app = create_app(Config(tmp_path / "data", local_tts=False))
    with TestClient(app, base_url=URL) as client:
        authenticate(client, app)
        yield app, client


def test_coding_analyze_endpoint(api_client, tmp_path):
    app, client = api_client
    workspace = tmp_path / "data/workspace"
    sample = workspace / "math_module.py"
    sample.write_text("def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    res = client.post("/api/coding/analyze", json={"path": str(sample)})
    assert res.status_code == 200
    data = res.json()
    assert data["language"] == "python"
    assert len(data["functions"]) == 1
    assert data["functions"][0]["name"] == "add"


def test_coding_generate_and_security_audit(api_client):
    app, client = api_client

    # 1. Safe code generation
    res = client.post(
        "/api/coding/generate",
        json={"path": "calc.py", "content": "def multiply(x, y):\n    return x * y\n"},
    )
    assert res.status_code == 200
    assert res.json()["success"] is True

    # 2. Dangerous code generation (eval rejected)
    res_bad = client.post(
        "/api/coding/generate",
        json={"path": "eval_test.py", "content": "def run():\n    eval('2+2')\n"},
    )
    assert res_bad.status_code == 422
    assert "AST Security Audit Rejected" in res_bad.json()["error"]

    # 3. Protected file rejected with 403
    res_prot = client.post(
        "/api/coding/generate",
        json={"path": "security.py", "content": "# overwrite attempt\n"},
    )
    assert res_prot.status_code == 403


def test_coding_refactor_endpoint(api_client):
    app, client = api_client
    edits = [
        {"path": "service_a.py", "new_content": "SERVICE_VERSION = 1\n"},
        {"path": "service_b.py", "new_content": "SERVICE_VERSION = 2\n"},
    ]
    res = client.post("/api/coding/refactor", json={"edits": edits})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert len(data["modified_files"]) == 2


def test_coding_git_status_endpoint(api_client):
    app, client = api_client
    res = client.post("/api/coding/git/status", json={})
    assert res.status_code == 200
    assert "clean" in res.json()


def test_creative_blender_endpoints(api_client, tmp_path):
    app, client = api_client

    # 1. Status
    res_stat = client.get("/api/creative/blender/status")
    assert res_stat.status_code == 200
    assert "procedural_3d_mesh_synthesis" in res_stat.json()["capabilities"]

    # 2. Generate Mesh
    out_glb = tmp_path / "cube_test.glb"
    res_mesh = client.post(
        "/api/creative/blender/generate_mesh",
        json={"mesh_type": "cube", "output_format": "glb", "output_path": str(out_glb)},
    )
    assert res_mesh.status_code == 200
    assert res_mesh.json()["success"] is True
    assert out_glb.exists()

    # 3. Render Mesh
    out_png = tmp_path / "cube_render.png"
    res_render = client.post(
        "/api/creative/blender/render",
        json={"mesh_type": "cube", "resolution": [320, 240], "output_path": str(out_png)},
    )
    assert res_render.status_code == 200
    assert res_render.json()["success"] is True
    assert out_png.exists()


def test_creative_godot_endpoints(api_client, tmp_path):
    app, client = api_client

    # 1. Status
    res_stat = client.get("/api/creative/godot/status")
    assert res_stat.status_code == 200

    # 2. Create Project
    proj_dir = tmp_path / "MyGodotGame"
    res_proj = client.post(
        "/api/creative/godot/create_project",
        json={"project_name": "MyGodotGame", "target_dir": str(proj_dir)},
    )
    assert res_proj.status_code == 200
    assert "project.godot" in res_proj.json()["files_created"]

    # 3. Create Scene
    res_scene = client.post(
        "/api/creative/godot/create_scene",
        json={"project_dir": str(proj_dir), "scene_name": "Enemy", "archetype": "2d_character"},
    )
    assert res_scene.status_code == 200
    assert res_scene.json()["root_type"] == "CharacterBody2D"

    # 4. Inspect Project
    res_inspect = client.post(
        "/api/creative/godot/inspect",
        json={"project_dir": str(proj_dir)},
    )
    assert res_inspect.status_code == 200
    assert res_inspect.json()["valid"] is True
    assert len(res_inspect.json()["scenes"]) >= 2


def test_creative_unreal_endpoints(api_client, tmp_path):
    app, client = api_client

    # 1. Status
    res_stat = client.get("/api/creative/unreal/status")
    assert res_stat.status_code == 200

    # 2. Generate Script
    out_script = tmp_path / "spawn_prop.py"
    res_script = client.post(
        "/api/creative/unreal/generate_script",
        json={
            "task_type": "spawn_actor",
            "actor_class": "StaticMeshActor",
            "parameters": {"label": "Pillar"},
            "output_path": str(out_script),
        },
    )
    assert res_script.status_code == 200
    assert res_script.json()["task_type"] == "spawn_actor"
    assert out_script.exists()
    assert "Pillar" in out_script.read_text(encoding="utf-8")
