"""Real SQLite/file/process migration checks against isolated synthetic data."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from sight_core.brain_store import BrainStore
from sight_core.cli import main, single_instance
from sight_core.memory import MemoryInput, MemoryService
from sight_core import migration
from sight_core.security import canonical
from sight_core.store import Store


ROOT = Path(__file__).resolve().parents[1]


def file_hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and p.name not in ("service.lock", migration.MARKER)}


@pytest.mark.parametrize("configuration_only", [False, True])
def test_empty_and_configuration_only_migration_do_not_invent_databases(tmp_path, configuration_only):
    source, backup = tmp_path / "owner", tmp_path / "backup"
    source.mkdir()
    if configuration_only:
        (source / "local-model.json").write_bytes(b'{"model":"gemma4:e4b-it-qat","thinking":true}\n')
    before = file_hashes(source)
    result = migration.migrate_identity(source, backup)
    assert result["status"] == "migrated" and result["version"] == 1
    assert result["data_moved"] is False and result["requires_reauthorization"] is False
    manifest = migration.verify_migration_backup(backup)
    assert manifest["partial_installation"] is True
    assert set(manifest["files"]) == ({"local-model.json"} if configuration_only else set())
    assert not list(source.glob("*.sqlite3")) and not list(backup.glob("*.sqlite3"))
    assert file_hashes(source) == before
    original_marker = (source / migration.MARKER).read_bytes()
    assert migration.migrate_identity(source, backup)["status"] == "already_migrated"
    assert (source / migration.MARKER).read_bytes() == original_marker
    assert file_hashes(source) == before


def test_full_migration_preserves_memories_quotas_credentials_and_database_formats(tmp_path, monkeypatch):
    source, backup = tmp_path / "legacy", tmp_path / "backup"
    store = Store(source)
    brain = BrainStore(source)
    memory = MemoryService(brain)
    record = memory.put(MemoryInput(key="project.name", content="SIGHT is my archived project name", privacy_scope="local"))
    store.set_setting("provider.groq", {"enabled": True, "daily_request_limit": 7})
    assert store.reserve_cloud("groq", "synthetic-day", 0, 7, 0)
    store.set_setting("phase3.monitor", {"enabled": True})
    (source / "local-model.json").write_text('{"model":"gemma4:e4b-it-qat","thinking":true}')
    (source / "files").mkdir()
    (source / "files" / "note.txt").write_text("Original owner text containing SIGHT")
    (source / "artifacts").mkdir()
    (source / "artifacts" / "fixture.txt").write_text("Synthetic artifact")
    (source / "browser-token").write_text("synthetic-launch-token")
    (source / "events.log").write_text("synthetic local log")
    before = file_hashes(source)
    def reject_vault(*args, **kwargs):
        pytest.fail("Migration must not read or write OS credentials")
    import keyring
    monkeypatch.setattr(keyring, "get_password", reject_vault)
    monkeypatch.setattr(keyring, "set_password", reject_vault)
    result = migration.migrate_identity(source, backup)
    assert result["backup"]["partial_installation"] is False
    assert set(migration.verify_migration_backup(backup)["files"]) == {
        "sight.sqlite3", "brain.sqlite3", "local-model.json", "files/note.txt", "artifacts/fixture.txt"}
    assert file_hashes(source) == before
    assert memory.get(record["id"])["content"] == "SIGHT is my archived project name"
    with sqlite3.connect(backup / "sight.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert json.loads(db.execute("SELECT value FROM settings WHERE key='usage.groq.synthetic-day'").fetchone()[0])["requests"] == 1
        assert json.loads(db.execute("SELECT value FROM settings WHERE key='provider.groq'").fetchone()[0])["enabled"] is True
    with sqlite3.connect(backup / "brain.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] in (2, 3)
        assert db.execute("SELECT content FROM profiles WHERE id=?", (record["id"],)).fetchone()[0] == record["content"]
    assert not (backup / "browser-token").exists() and not (backup / "events.log").exists()


def test_one_existing_database_is_backed_up_without_creating_the_other(tmp_path):
    source = tmp_path / "owner"
    Store(source).set_setting("usage.test.day", {"requests": 4})
    result = migration.migrate_identity(source, tmp_path / "backup")
    assert result["backup"]["partial_installation"] is True
    assert not (source / "brain.sqlite3").exists()
    assert set(migration.verify_migration_backup(tmp_path / "backup")["files"]) == {"sight.sqlite3"}


def test_running_server_blocks_migration_before_backup_or_marker(tmp_path):
    source, backup = tmp_path / "owner", tmp_path / "backup"
    with single_instance(source):
        with pytest.raises(RuntimeError, match="server owns"):
            migration.migrate_identity(source, backup)
    assert not backup.exists() and not (source / migration.MARKER).exists()


@pytest.mark.parametrize("value", [{"format": migration.RECORD_FORMAT, "version": 2, "to": "BEL"},
                                   {"format": migration.RECORD_FORMAT, "version": True, "to": "BEL"},
                                   ["invalid"], None])
def test_unknown_or_invalid_migration_record_is_never_overwritten(tmp_path, value):
    source = tmp_path / "owner"
    source.mkdir()
    marker = source / migration.MARKER
    marker.write_text(json.dumps(value))
    before = marker.read_bytes()
    with pytest.raises(ValueError, match="migration record"):
        migration.migrate_identity(source, tmp_path / "backup")
    assert marker.read_bytes() == before and not (tmp_path / "backup").exists()


def test_corrupt_backup_is_not_reported_as_verified_on_repeat(tmp_path):
    source, backup = tmp_path / "owner", tmp_path / "backup"
    source.mkdir()
    (source / "local-model.json").write_text('{"model":"gemma4:e4b-it-qat"}')
    migration.migrate_identity(source, backup)
    marker = (source / migration.MARKER).read_bytes()
    (backup / "local-model.json").write_text("corrupted")
    with pytest.raises(ValueError, match="hash mismatch"):
        migration.migrate_identity(source)
    assert (source / migration.MARKER).read_bytes() == marker


def test_copied_identity_record_does_not_claim_credentials_migrated(tmp_path):
    source = tmp_path / "owner"
    source.mkdir()
    migration.migrate_identity(source, tmp_path / "backup")
    copied = tmp_path / "copied"
    shutil.copytree(source, copied)
    with pytest.raises(ValueError, match="reauthorization"):
        migration.migrate_identity(copied)


def test_backup_failure_preserves_source_and_writes_no_marker(tmp_path, monkeypatch):
    source, backup = tmp_path / "owner", tmp_path / "backup"
    source.mkdir()
    (source / "local-model.json").write_text('{"model":"gemma4:e4b-it-qat","thinking":true}')
    before = file_hashes(source)
    def failed_copy(*args):
        raise OSError("Synthetic disk failure")
    monkeypatch.setattr(migration, "exclusive_copy", failed_copy)
    with pytest.raises(OSError, match="Synthetic disk"):
        migration.migrate_identity(source, backup)
    assert file_hashes(source) == before
    assert not (source / migration.MARKER).exists()
    assert backup.exists()  # Retained for inspection, never deleted by a retry.


def test_actual_process_termination_after_verified_backup_can_retry_safely(tmp_path):
    source, first, second = tmp_path / "owner", tmp_path / "first", tmp_path / "second"
    source.mkdir()
    (source / "local-model.json").write_text('{"model":"gemma4:e4b-it-qat","thinking":true}')
    before = file_hashes(source)
    code = """import os,sys
from pathlib import Path
from sight_core import migration
original=migration.atomic_private_write
def stop_before_marker(path,content):
    if Path(path).name==migration.MARKER:os._exit(23)
    return original(path,content)
migration.atomic_private_write=stop_before_marker
migration.migrate_identity(Path(sys.argv[1]),Path(sys.argv[2]))
"""
    child = subprocess.run([sys.executable, "-c", code, str(source), str(first)], cwd=ROOT,
                           capture_output=True, text=True, timeout=20,
                           creationflags=0x08000000 if os.name == "nt" else 0)
    assert child.returncode == 23, child.stderr
    assert not (source / migration.MARKER).exists()
    assert set(migration.verify_migration_backup(first)["files"]) == {"local-model.json"}
    assert file_hashes(source) == before
    assert migration.migrate_identity(source, second)["status"] == "migrated"
    assert file_hashes(source) == before


def test_hardlinked_configuration_is_rejected_before_backup(tmp_path):
    source = tmp_path / "owner"
    source.mkdir()
    original = tmp_path / "configuration.json"
    original.write_text('{"model":"gemma4:e4b-it-qat"}')
    os.link(original, source / "local-model.json")
    with pytest.raises(ValueError, match="hardlink"):
        migration.migrate_identity(source, tmp_path / "backup")
    assert not (tmp_path / "backup").exists() and not (source / migration.MARKER).exists()


def test_backup_must_be_new_and_outside_data_directory(tmp_path):
    source = tmp_path / "owner"
    source.mkdir()
    with pytest.raises(ValueError, match="outside"):
        migration.migrate_identity(source, source / "backup")
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep.txt").write_text("Keep this")
    with pytest.raises(ValueError, match="new directory"):
        migration.migrate_identity(source, existing)
    assert (existing / "keep.txt").read_text() == "Keep this"


def test_cli_explicit_directory_does_not_read_or_mutate_default_owner(tmp_path, monkeypatch, capsys):
    source = tmp_path / "selected"
    source.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "local-model.json").write_text("invalid unrelated configuration")
    monkeypatch.setenv("BEL_DATA_DIR", str(unrelated))
    assert main(["migrate", "--data-directory", str(source), "--backup-directory", str(tmp_path / "backup")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "migrated"
    assert not (unrelated / migration.MARKER).exists()
    assert (unrelated / "local-model.json").read_text() == "invalid unrelated configuration"
