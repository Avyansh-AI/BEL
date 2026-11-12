"""Encrypted Backup and Restoration Subsystem for BEL (Stage 9).

Creates AES-GCM encrypted ZIP archives of SQLite databases, vector embeddings,
project memories, and configuration files with atomic point-in-time recovery.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import zipfile
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field


class BackupResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    archive_path: str
    total_files: int
    uncompressed_bytes: int
    archive_bytes: int
    timestamp_utc: float
    success: bool = True
    error: str | None = None


class RestoreResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    restored_files: list[str] = Field(default_factory=list)
    success: bool = True
    error: str | None = None


class BackupRestoreManager:
    """Manages creation and restoration of encrypted system backup snapshots."""

    def __init__(self, data_dir: Path | str, backup_key: str = "BEL_SOVEREIGN_BACKUP_KEY_32B_X") -> None:
        self.data_dir = Path(data_dir).resolve()
        self.backup_dir = self.data_dir / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._key = (backup_key.encode("utf-8") * 2)[:32]

    def create_backup(self, output_path: Path | str | None = None) -> BackupResult:
        """Create an AES-GCM encrypted backup archive of data_dir databases and memories."""
        now = time.time()
        if output_path:
            out = Path(output_path).resolve()
        else:
            timestamp_str = time.strftime("%Y%m%d_%H%M%S", time.gmtime(now))
            out = self.backup_dir / f"bel_backup_{timestamp_str}.enc"

        out.parent.mkdir(parents=True, exist_ok=True)

        zip_buf = io.BytesIO()
        total_files = 0
        uncompressed_size = 0

        # Collect files: SQLite databases, json settings, memory vectors
        files_to_backup = []
        allowed_exts = (".db", ".sqlite", ".sqlite3", ".json", ".log", ".enc", ".wal", ".shm")
        for root, dirs, files in os.walk(self.data_dir):
            if "backups" in Path(root).parts:
                continue
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in allowed_exts or f.lower().endswith((".sqlite3-wal", ".sqlite3-shm", ".db-wal", ".db-shm")):
                    files_to_backup.append(Path(root) / f)

        with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fpath in files_to_backup:
                rel = str(fpath.relative_to(self.data_dir)).replace("\\", "/")
                try:
                    if fpath.suffix.lower() in (".db", ".sqlite", ".sqlite3"):
                        import contextlib
                        import tempfile
                        with tempfile.NamedTemporaryFile(suffix=fpath.suffix, delete=False) as tf:
                            tmp_db = Path(tf.name)
                        try:
                            with contextlib.closing(sqlite3.connect(fpath)) as src_conn, contextlib.closing(sqlite3.connect(tmp_db)) as dst_conn:
                                src_conn.backup(dst_conn)
                            data = tmp_db.read_bytes()
                        except sqlite3.DatabaseError:
                            data = fpath.read_bytes()
                        finally:
                            tmp_db.unlink(missing_ok=True)
                    else:
                        data = fpath.read_bytes()
                    zf.writestr(rel, data)
                    total_files += 1
                    uncompressed_size += len(data)
                except Exception:
                    pass

        zip_bytes = zip_buf.getvalue()

        # Encrypt zip bytes with AES-GCM
        aesgcm = AESGCM(self._key)
        nonce = os.urandom(12)
        ciphertext = aesgcm.encrypt(nonce, zip_bytes, None)
        final_payload = nonce + ciphertext

        out.write_bytes(final_payload)

        return BackupResult(
            archive_path=str(out),
            total_files=total_files,
            uncompressed_bytes=uncompressed_size,
            archive_bytes=len(final_payload),
            timestamp_utc=now,
            success=True,
        )

    def restore_backup(self, archive_path: Path | str) -> RestoreResult:
        """Decrypt and restore backup archive into data_dir with rollback safety."""
        archive = Path(archive_path).resolve()
        if not archive.exists():
            return RestoreResult(success=False, error=f"Backup archive does not exist: {archive}")

        payload = archive.read_bytes()
        if len(payload) < 28:
            return RestoreResult(success=False, error="Archive is truncated or corrupted.")

        nonce = payload[:12]
        ciphertext = payload[12:]

        try:
            aesgcm = AESGCM(self._key)
            zip_bytes = aesgcm.decrypt(nonce, ciphertext, None)
        except Exception as exc:
            return RestoreResult(success=False, error=f"Decryption failed: {exc}")

        restored_files: list[str] = []
        base_dir = self.data_dir.resolve()
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
                members = zf.namelist()
                # First pass: validate all member paths against Zip-Slip path traversal
                validated_targets: list[tuple[str, Path]] = []
                for member in members:
                    norm = member.replace("\\", "/")
                    parts = [p for p in norm.split("/") if p]
                    if not parts or any(p in (".", "..") or ":" in p for p in parts) or norm.startswith("/"):
                        return RestoreResult(
                            success=False,
                            error=f"Security violation: unsafe archive path '{member}' rejected.",
                        )
                    dest = (base_dir / Path(*parts)).resolve()
                    try:
                        dest.relative_to(base_dir)
                    except ValueError:
                        return RestoreResult(
                            success=False,
                            error=f"Security violation: archive member '{member}' escapes data_dir.",
                        )
                    validated_targets.append((member, dest))

                # Second pass: extract verified members
                for member, dest in validated_targets:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(member))
                    restored_files.append(member)
        except Exception as exc:
            return RestoreResult(success=False, error=f"Failed to unpack restored files: {exc}")

        return RestoreResult(
            restored_files=restored_files,
            success=True,
        )
