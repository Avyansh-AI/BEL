"""High-Level Codebase Engineering Orchestrator for BEL (Stage 7).

Coordinates static analysis, transactional multi-file editing, test verification,
and atomic Git repository management.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .code_analyzer import CodebaseAnalyzer
from .code_editor import CodeEditor
from .git_agent import GitAgent
from .models import (
    EditResult,
    FileAnalysis,
    FileEdit,
    GitResult,
    GitStatus,
    RepoAnalysis,
    TestRunResult,
)
from .test_runner import TestRunner


class CodeAgent:
    """Master software engineering agent for BEL."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()
        self.analyzer = CodebaseAnalyzer(self.workspace_root)
        self.editor = CodeEditor(self.workspace_root)
        self.runner = TestRunner(self.workspace_root)
        self.git = GitAgent(self.workspace_root)

    def analyze_path(self, target_path: Path | str) -> FileAnalysis | RepoAnalysis:
        p = Path(target_path)
        if not p.is_absolute():
            p = (self.workspace_root / p).resolve()

        if p.is_dir():
            return self.analyzer.analyze_directory(p)
        return self.analyzer.analyze_file(p)

    def find_symbol_references(self, symbol: str) -> list[str]:
        return self.analyzer.find_references(symbol, self.workspace_root)

    def apply_edits(self, edits: Sequence[FileEdit]) -> EditResult:
        return self.editor.apply_edits(edits)

    def write_file(self, file_path: Path | str, content: str) -> EditResult:
        return self.editor.write_file(file_path, content)

    def run_tests(
        self,
        test_type: str = "pytest",
        target: str | None = None,
        timeout_sec: int = 60,
    ) -> TestRunResult:
        return self.runner.run_tests(test_type=test_type, target=target, timeout_sec=timeout_sec)

    def git_status(self) -> GitStatus:
        return self.git.status(self.workspace_root)

    def git_create_branch(self, branch_name: str) -> GitResult:
        return self.git.create_branch(self.workspace_root, branch_name)

    def git_diff(self, staged: bool = False, file_path: str | None = None) -> str:
        return self.git.get_diff(self.workspace_root, staged=staged, file_path=file_path)

    def git_commit(
        self,
        message: str,
        paths: list[str] | None = None,
        conventional: bool = True,
    ) -> GitResult:
        return self.git.create_commit(
            self.workspace_root,
            message=message,
            paths=paths,
            conventional=conventional,
        )
