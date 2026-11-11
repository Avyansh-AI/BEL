"""Unit tests for Stage 7 Codebase Engineering Agent."""
from __future__ import annotations

import os
from pathlib import Path
import pytest
import tempfile

from sight_core.code_agent import (
    CodeAgent,
    CodeEditor,
    CodebaseAnalyzer,
    FileEdit,
    GitAgent,
    SecurityBoundaryViolation,
    TestRunner,
)


def test_codebase_analyzer_python():
    with tempfile.TemporaryDirectory() as tmp_dir:
        sample_file = Path(tmp_dir) / "sample.py"
        sample_file.write_text(
            '''"""Sample module docstring."""
import sys
from os import path

class DataProcessor:
    """Processor class."""
    def process_item(self, item: str) -> bool:
        return True

async def fetch_data(url: str) -> dict:
    """Async fetch function."""
    return {}
''',
            encoding="utf-8",
        )

        analyzer = CodebaseAnalyzer(tmp_dir)
        analysis = analyzer.analyze_file(sample_file)

        assert analysis.language == "python"
        assert analysis.total_lines > 10
        assert "sys" in analysis.imports
        assert "os.path" in analysis.imports

        # Verify class
        assert len(analysis.classes) == 1
        assert analysis.classes[0].name == "DataProcessor"
        assert len(analysis.classes[0].methods) == 1
        assert analysis.classes[0].methods[0].name == "process_item"

        # Verify function
        assert len(analysis.functions) == 1
        assert analysis.functions[0].name == "fetch_data"
        assert analysis.functions[0].is_async is True


def test_codebase_analyzer_directory_and_references():
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        f1 = root / "module_a.py"
        f1.write_text("class AlphaNode:\n    pass\n", encoding="utf-8")
        f2 = root / "module_b.py"
        f2.write_text("from module_a import AlphaNode\nnode = AlphaNode()\n", encoding="utf-8")

        analyzer = CodebaseAnalyzer(root)
        repo_analysis = analyzer.analyze_directory(root)

        assert repo_analysis.total_files == 2
        assert "AlphaNode" in repo_analysis.symbols

        refs = analyzer.find_references("AlphaNode", root)
        assert len(refs) == 2


def test_code_editor_workspace_boundary_enforcement():
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir) / "workspace"
        workspace.mkdir()
        editor = CodeEditor(workspace)

        # Attempt to write outside workspace
        outside_path = Path(tmp_dir) / "outside.txt"
        with pytest.raises(SecurityBoundaryViolation):
            editor.write_file(outside_path, "malicious content")

        # Attempt path traversal
        with pytest.raises(SecurityBoundaryViolation):
            editor.write_file("../../escaped.py", "malicious content")


def test_code_editor_protected_core_files_invariant():
    with tempfile.TemporaryDirectory() as tmp_dir:
        editor = CodeEditor(tmp_dir)

        # Attempt to overwrite protected kernel files
        for protected in ["security.py", "boundaries.py", "decision.py", "system_monitor.py"]:
            with pytest.raises(PermissionError):
                editor.write_file(protected, "# modified")


def test_code_editor_ast_security_audit():
    with tempfile.TemporaryDirectory() as tmp_dir:
        editor = CodeEditor(tmp_dir)

        # Dangerous code with eval
        eval_code = "def dangerous():\n    eval('2+2')\n"
        res = editor.write_file("test_eval.py", eval_code)
        assert res.success is False
        assert "Prohibited dynamic evaluation" in (res.error or "")

        # Dangerous code with os.system
        system_code = "import os\ndef bad():\n    os.system('dir')\n"
        res = editor.write_file("test_sys.py", system_code)
        assert res.success is False
        assert "Prohibited system call" in (res.error or "")


def test_code_editor_atomic_rollback():
    with tempfile.TemporaryDirectory() as tmp_dir:
        editor = CodeEditor(tmp_dir)
        file_a = Path(tmp_dir) / "file_a.py"
        file_a.write_text("initial_state = 1\n", encoding="utf-8")

        # Edit 1 is valid, but Edit 2 triggers AST security violation
        edits = [
            FileEdit(path="file_a.py", new_content="initial_state = 2\n"),
            FileEdit(path="file_b.py", new_content="import os\nos.system('whoami')\n"),
        ]

        result = editor.apply_edits(edits)
        assert result.success is False

        # file_a must be rolled back to initial_state = 1
        assert file_a.read_text(encoding="utf-8") == "initial_state = 1\n"
        # file_b must NOT exist
        assert not (Path(tmp_dir) / "file_b.py").exists()


def test_git_agent_commit_convention_and_safety():
    with tempfile.TemporaryDirectory() as tmp_dir:
        git = GitAgent(tmp_dir)
        if not git.is_git_available():
            pytest.skip("Git executable not available in environment")

        # Initialize mock repo
        import subprocess
        subprocess.run(["git", "init"], cwd=tmp_dir, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "bel@test.local"], cwd=tmp_dir, check=True)
        subprocess.run(["git", "config", "user.name", "BEL Test"], cwd=tmp_dir, check=True)

        assert git.is_repo(tmp_dir) is True

        # Test prohibited flag protection
        with pytest.raises(PermissionError):
            git._run_git(tmp_dir, ["reset", "--hard", "HEAD"])

        # Create file
        (Path(tmp_dir) / "app.py").write_text("print('hello')\n")
        status = git.status(tmp_dir)
        assert status.clean is False
        assert "app.py" in status.untracked

        # Non-conventional commit should be rejected
        res = git.create_commit(tmp_dir, "added app file", conventional=True)
        assert res.success is False
        assert "Conventional Commits" in (res.error or "")

        # Conventional commit succeeds
        res = git.create_commit(tmp_dir, "feat(core): initial app setup", conventional=True)
        assert res.success is True
        assert res.commit_hash is not None

        # Verify status is now clean
        status2 = git.status(tmp_dir)
        assert status2.clean is True


def test_test_runner_pytest():
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_file = Path(tmp_dir) / "test_simple.py"
        test_file.write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")

        runner = TestRunner(tmp_dir)
        res = runner.run_tests(test_type="pytest", target="test_simple.py")

        assert res.success is True
        assert res.passed == 1
        assert res.failed == 0
