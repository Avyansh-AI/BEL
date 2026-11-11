"""Unit tests for Stage 9 Binary and Dependency Integrity Auditor."""
from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from sight_core.integrity_audit import IntegrityAuditor


def test_integrity_auditor_pass_and_tamper_detection():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        f1 = root / "core.py"
        f1.write_text("print('core')", encoding="utf-8")
        f2 = root / "helper.py"
        f2.write_text("def help(): pass", encoding="utf-8")

        auditor = IntegrityAuditor(root)
        manifest = auditor.generate_manifest(target_files=[f1, f2])

        assert "core.py" in manifest
        assert "helper.py" in manifest

        # 1. Unmodified audit must pass
        res_ok = auditor.verify_integrity(manifest)
        assert res_ok.passed is True
        assert res_ok.total_files_audited == 2
        assert len(res_ok.corrupted_files) == 0

        # 2. Tamper f1
        f1.write_text("print('tampered')", encoding="utf-8")
        res_tampered = auditor.verify_integrity(manifest)
        assert res_tampered.passed is False
        assert "core.py" in res_tampered.corrupted_files

        # 3. Missing f2
        f2.unlink()
        res_missing = auditor.verify_integrity(manifest)
        assert res_missing.passed is False
        assert "helper.py" in res_missing.missing_files
