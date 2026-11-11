"""BEL Code Agent Package (Stage 7)."""
from .code_analyzer import CodebaseAnalyzer
from .code_editor import CodeEditor, SecurityBoundaryViolation
from .git_agent import GitAgent
from .models import (
    ClassInfo,
    EditResult,
    FileAnalysis,
    FileEdit,
    FunctionInfo,
    GitResult,
    GitStatus,
    RepoAnalysis,
    TestRunResult,
)
from .orchestrator import CodeAgent
from .test_runner import TestRunner

__all__ = [
    "ClassInfo",
    "CodeAgent",
    "CodeEditor",
    "CodebaseAnalyzer",
    "EditResult",
    "FileAnalysis",
    "FileEdit",
    "FunctionInfo",
    "GitAgent",
    "GitResult",
    "GitStatus",
    "RepoAnalysis",
    "SecurityBoundaryViolation",
    "TestRunResult",
    "TestRunner",
]
