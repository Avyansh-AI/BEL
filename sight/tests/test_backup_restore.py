"""Unit tests for Stage 9 Encrypted Backup and Restoration Subsystem."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from sight_core.backup_restore import BackupRestoreManager


def test_backup_and_restore_cycle():
    with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dest_dir:
        # Create mock data in source
        src_path = Path(src_dir)
        (src_path / "bel.db").write_text("SQLITE_FORMAT_MOCK_DATA")
        (src_path / "settings.json").write_text('{"theme": "dark", "owner": "Tony"}')

        mgr_src = BackupRestoreManager(src_path)
        backup_res = mgr_src.create_backup()

        assert backup_res.success is True
        assert backup_res.total_files == 2
        assert Path(backup_res.archive_path).exists()

        # Archive cannot be read as plain text or plain zip
        raw_archive = Path(backup_res.archive_path).read_bytes()
        assert b"PK\x03\x04" not in raw_archive[:4]  # First 4 bytes are nonce, not ZIP header

        # Restore into destination
        dest_path = Path(dest_dir)
        mgr_dest = BackupRestoreManager(dest_path)
        restore_res = mgr_dest.restore_backup(backup_res.archive_path)

        assert restore_res.success is True
        assert "bel.db" in restore_res.restored_files
        assert "settings.json" in restore_res.restored_files

        # Verify restored files match
        assert (dest_path / "bel.db").read_text() == "SQLITE_FORMAT_MOCK_DATA"
        assert '{"theme": "dark", "owner": "Tony"}' in (dest_path / "settings.json").read_text()
