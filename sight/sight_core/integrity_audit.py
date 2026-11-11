"""Dependency and Binary File Integrity Auditor for BEL (Stage 9).

Performs cryptographic SHA-256 hash auditing across Python packages,
critical binary assets, and protected kernel source files to detect tampering
or file corruption.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

from .rsi.boundaries import PROTECTED_CORE_FILES


class FileHashRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")
    relative_path: str
    sha256_hash: str
    size_bytes: int


class IntegrityAuditResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    total_files_audited: int = 0
    passed: bool = True
    corrupted_files: list[str] = Field(default_factory=list)
    missing_files: list[str] = Field(default_factory=list)
    timestamp_utc: float = 0.0


class IntegrityAuditor:
    """Computes and verifies cryptographic SHA-256 checksums."""

    def __init__(self, root_dir: Path | str, manifest_path: Path | str | None = None) -> None:
        self.root_dir = Path(root_dir).resolve()
        self.manifest_path = Path(manifest_path).resolve() if manifest_path else self.root_dir / "integrity_manifest.json"

    @staticmethod
    def compute_sha256(file_path: Path | str) -> str:
        """Compute SHA-256 hex digest of a file in 64 KB blocks."""
        p = Path(file_path)
        hasher = hashlib.sha256()
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def generate_manifest(self, target_files: Sequence[Path | str] | None = None) -> dict[str, str]:
        """Generate a dictionary mapping relative paths to SHA-256 hashes."""
        manifest: dict[str, str] = {}

        if target_files:
            files_to_hash = [Path(f) for f in target_files]
        else:
            # Audit core files and protected python files
            files_to_hash = []
            for p in self.root_dir.rglob("*.py"):
                if "__pycache__" not in p.parts and ".venv" not in p.parts:
                    files_to_hash.append(p)

        for p in files_to_hash:
            if p.is_file():
                rel = str(p.relative_to(self.root_dir)).replace("\\", "/")
                manifest[rel] = self.compute_sha256(p)

        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest

    def verify_integrity(self, expected_manifest: dict[str, str] | None = None) -> IntegrityAuditResult:
        """Verify files on disk against expected manifest."""
        import time
        if expected_manifest is None:
            if not self.manifest_path.exists():
                return IntegrityAuditResult(
                    total_files_audited=0,
                    passed=False,
                    missing_files=["integrity_manifest.json"],
                    timestamp_utc=time.time(),
                )
            expected_manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))

        corrupted: list[str] = []
        missing: list[str] = []
        audited = 0

        for rel_path, expected_hash in expected_manifest.items():
            full_path = self.root_dir / rel_path
            if not full_path.exists():
                missing.append(rel_path)
                continue

            audited += 1
            actual_hash = self.compute_sha256(full_path)
            if actual_hash != expected_hash:
                corrupted.append(rel_path)

        passed = len(corrupted) == 0 and len(missing) == 0

        return IntegrityAuditResult(
            total_files_audited=audited,
            passed=passed,
            corrupted_files=corrupted,
            missing_files=missing,
            timestamp_utc=time.time(),
        )
