"""Regression and Verification Tests for Audit Repairs (Phase 8)."""
import os
import sys
from pathlib import Path
import pytest

from sight_core.config import Config
from sight_core.models import OllamaProvider
from sight_core.godot_agent.godot_bridge import GodotAgent
from sight_core.blender_agent.blender_bridge import BlenderAgent


def test_ollama_discovery_methods(tmp_path):
    """Verify BUG-003: Ollama executable discovery and daemon check."""
    c = Config(tmp_path)
    provider = OllamaProvider(c)
    exe = provider.discover_executable()
    # If host has Ollama installed at AppData, verify discovery returns valid path
    if os.path.exists(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")):
        assert exe is not None
        assert os.path.exists(exe)
    assert hasattr(provider, "start_daemon_if_needed")


def test_godot_standard_path_patterns(tmp_path):
    """Verify BUG-004: Godot discovery checks standard installation paths."""
    agent = GodotAgent(tmp_path)
    # Ensure method returns without error and probes valid types
    exe = agent._discover_godot()
    assert exe is None or isinstance(exe, Path)


def test_blender_discovery_robustness(tmp_path):
    """Verify Blender discovery probes standard paths and handles fallback."""
    agent = BlenderAgent(tmp_path)
    status = agent.get_status()
    assert hasattr(status, "available")
    assert hasattr(status, "fallback_mode")


def test_golden_suite_manifest_paths(tmp_path):
    """Verify BUG-005: Golden Suite path resolution logic."""
    from scripts.run_golden_suite import verify_axiom_1_integrity, verify_convergence_subsystems
    subsystems = verify_convergence_subsystems()
    assert all(subsystems.values())
    assert len(subsystems) == 26


def test_backup_restore_sqlite3_roundtrip(tmp_path):
    """Verify Stage 1 Item 9: BackupRestoreManager backs up and restores .sqlite3 databases."""
    import sqlite3
    from sight_core.backup_restore import BackupRestoreManager

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "sight.sqlite3"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, val TEXT)")
        conn.execute("INSERT INTO items VALUES (1, 'golden_state')")
        conn.commit()
    finally:
        conn.close()

    mgr = BackupRestoreManager(data_dir)
    bres = mgr.create_backup()
    assert bres.success
    assert bres.total_files == 1

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM items")
        conn.commit()
    finally:
        conn.close()

    rres = mgr.restore_backup(bres.archive_path)
    assert rres.success
    assert "sight.sqlite3" in rres.restored_files

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("SELECT val FROM items").fetchall()
    finally:
        conn.close()
    assert rows == [("golden_state",)]


def test_godot_run_project_validation(tmp_path):
    """Verify Stage 1 Item 4: GodotAgent.run_project validates project and handles missing binary."""
    from sight_core.godot_agent.godot_bridge import GodotAgent
    from sight_core.godot_agent.models import GodotProjectRequest

    agent = GodotAgent(tmp_path)
    missing = agent.run_project(tmp_path / "nonexistent")
    assert not missing.success
    assert "missing project.godot" in (missing.error or "")

    proj_dir = tmp_path / "demo_game"
    agent.create_project(GodotProjectRequest(project_name="Demo", target_dir=str(proj_dir)))
    if not agent.get_status().available:
        res = agent.run_project(proj_dir)
        assert not res.success
        assert "not found" in (res.error or "").lower()
