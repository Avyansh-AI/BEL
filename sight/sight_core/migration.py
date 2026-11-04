"""Explicit, versioned in-place identity migration; user records are never rewritten.

The snapshot format intentionally supports partial installations. It is distinct
from the full owner-data restore format, which requires both databases. This
utility does not copy credentials or activate restored data.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from .config import read_local_model
from .identity import APP_NAME, LEGACY_APP_NAME, identity
from .recovery import (DATABASES, MAX_BYTES, MAX_FILES, allowed, checksum,
                       exclusive_copy, validate_database)
from .security import atomic_private_write, canonical, private_directory, reject_links, safe_file

VERSION = 1
MARKER = "bel-migration.json"
BACKUP_FORMAT = "bel-identity-backup-v1"
RECORD_FORMAT = "bel-identity-migration-v1"


def directory_identity(directory):
    return hashlib.sha256(str(Path(directory).resolve()).encode("utf-8")).hexdigest()


def _inventory(source):
    read_local_model(source)
    files = []
    for name, versions in DATABASES.items():
        path = safe_file(source / name)
        if path.exists():
            validate_database(path, versions)
            files.append(path)
    brain = source / "brain.sqlite3"
    if brain.exists():
        with sqlite3.connect(brain.as_uri() + "?mode=ro", uri=True) as db:
            if db.execute("SELECT COUNT(*) FROM receipts WHERE state!='complete'").fetchone()[0]:
                raise ValueError("Unresolved file receipts require recovery before migration")
    if (source / "local-model.json").exists():
        files.append(safe_file(source / "local-model.json"))
    for folder in ("files", "artifacts"):
        root = reject_links(source / folder)
        if root.exists():
            if not root.is_dir():
                raise ValueError("Migration workspace must be a directory")
            for path in sorted(root.iterdir()):
                safe_file(path)
                if not allowed(path.relative_to(source).as_posix()):
                    raise ValueError("Unsupported migration snapshot file")
                files.append(path)
    if len(files) > MAX_FILES or sum(p.stat().st_size for p in files) > MAX_BYTES:
        raise ValueError("Migration snapshot exceeds the recovery limits")
    return files


def verify_migration_backup(directory):
    """Verify the exact partial/full snapshot without creating missing databases."""
    directory = reject_links(directory).resolve()
    manifest_path = safe_file(directory / "manifest.json")
    hash_path = safe_file(directory / "manifest.sha256")
    if manifest_path.stat().st_size > 2_000_000 or hash_path.stat().st_size > 100:
        raise ValueError("Invalid migration backup manifest size")
    if checksum(manifest_path) != hash_path.read_text(encoding="ascii").strip():
        raise ValueError("Migration backup manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (not isinstance(manifest, dict) or manifest.get("format") != BACKUP_FORMAT
            or not isinstance(manifest.get("files"), dict) or len(manifest["files"]) > MAX_FILES):
        raise ValueError("Invalid migration backup manifest")
    total = 0
    for name, row in manifest["files"].items():
        if (not allowed(name) or not isinstance(row, dict) or type(row.get("bytes")) is not int
                or row["bytes"] < 0):
            raise ValueError("Invalid migration backup entry")
        path = safe_file(directory / name)
        total += row["bytes"]
        if total > MAX_BYTES or path.stat().st_size != row["bytes"] or checksum(path) != row.get("sha256"):
            raise ValueError("Migration backup file size or hash mismatch")
        if name in DATABASES:
            validate_database(path, DATABASES[name])
    actual = set()
    for path in directory.rglob("*"):
        reject_links(path)
        if path.is_file():
            actual.add(path.relative_to(directory).as_posix())
    if actual != set(manifest["files"]) | {"manifest.json", "manifest.sha256"}:
        raise ValueError("Unmanifested migration backup file")
    read_local_model(directory)
    return manifest


def _snapshot(source, destination):
    files = _inventory(source)
    before = {p.relative_to(source).as_posix(): checksum(p) for p in files}
    private_directory(destination)
    rows = {}
    for path in files:
        name = path.relative_to(source).as_posix()
        target = destination / name
        if name in DATABASES:
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(target) as dst:
                src.backup(dst)
            validate_database(target, DATABASES[name])
        else:
            exclusive_copy(path, target)
        rows[name] = {"bytes": target.stat().st_size, "sha256": checksum(target)}
    # Respectful BEL/SIGHT processes are locked out; detect other changes too.
    after = {p.relative_to(source).as_posix(): checksum(p) for p in _inventory(source)}
    if before != after:
        raise ValueError("Data changed during migration backup; no identity metadata was written")
    manifest = {"format": BACKUP_FORMAT, "created_utc": datetime.now(timezone.utc).isoformat(),
                "files": rows, "source_directory_identity": directory_identity(source),
                "scope": "Existing supported databases, workspace files, artifacts and local model selection only",
                "excluded": ["credentials", "sessions", "logs", "voice recordings", "model weights", "code snapshots"],
                "partial_installation": not DATABASES.keys() <= rows.keys()}
    encoded = canonical(manifest).encode("utf-8")
    atomic_private_write(destination / "manifest.json", encoded)
    atomic_private_write(destination / "manifest.sha256", (hashlib.sha256(encoded).hexdigest() + "\n").encode("ascii"))
    verify_migration_backup(destination)
    return manifest


def _existing(source):
    path = safe_file(source / MARKER)
    if not path.exists():
        return None
    if path.stat().st_size > 16000:
        raise ValueError("Invalid BEL migration record size")
    record = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(record, dict) or record.get("format") != RECORD_FORMAT
            or type(record.get("version")) is not int or record["version"] != VERSION
            or record.get("to") != APP_NAME):
        raise ValueError("Unsupported or invalid BEL migration record; refusing to overwrite it")
    if record.get("data_directory_identity") != directory_identity(source):
        raise ValueError("Copied data directory requires explicit credential reauthorization; in-place migration only")
    backup = record.get("backup")
    if not isinstance(backup, dict) or not isinstance(backup.get("directory"), str):
        raise ValueError("Invalid BEL migration backup reference")
    manifest = verify_migration_backup(backup["directory"])
    if (checksum(Path(backup["directory"]) / "manifest.json") != backup.get("manifest_sha256")
            or manifest.get("source_directory_identity") != directory_identity(source)):
        raise ValueError("BEL migration backup reference mismatch")
    return record


def migrate_identity(data_dir, backup_directory=None):
    """Back up existing supported data, then atomically record BEL identity v1.

    Explicit call only. No data directory move, DB schema change, credential read,
    quota reset or automatic server activation occurs. Incomplete backup folders
    are retained after failures; a later attempt must use a new destination.
    """
    from .cli import single_instance
    source = reject_links(data_dir).resolve()
    if not source.is_dir():
        raise ValueError("Migration requires an existing data directory")
    with single_instance(source):
        record = _existing(source)
        if record is not None:
            return {"status": "already_migrated", "version": VERSION, "identity": identity(),
                    "data_directory": str(source), "backup": record["backup"],
                    "data_moved": False, "requires_reauthorization": False}
        if backup_directory is None:
            backup_directory = source.parent / (source.name + "-migration-backups") / ("bel-v1-" + uuid.uuid4().hex)
        destination = reject_links(backup_directory).resolve()
        if destination.exists():
            raise ValueError("Migration backup requires a new directory")
        if destination.is_relative_to(source) or source.is_relative_to(destination):
            raise ValueError("Migration backup must be outside the data directory")
        manifest = _snapshot(source, destination)
        backup = {"directory": str(destination), "manifest_sha256": checksum(destination / "manifest.json"),
                  "files": len(manifest["files"]), "partial_installation": manifest["partial_installation"]}
        record = {"format": RECORD_FORMAT, "version": VERSION, "from": LEGACY_APP_NAME, "to": APP_NAME,
                  "created_utc": datetime.now(timezone.utc).isoformat(),
                  "data_directory_identity": directory_identity(source), "backup": backup,
                  "storage_policy": "Existing database names, record contents, quota ledgers and OS-vault namespaces retained in place"}
        atomic_private_write(source / MARKER, canonical(record).encode("utf-8"))
        return {"status": "migrated", "version": VERSION, "identity": identity(),
                "data_directory": str(source), "backup": backup,
                "data_moved": False, "requires_reauthorization": False}
