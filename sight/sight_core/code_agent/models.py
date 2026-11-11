"""Data models for BEL Code Agent (Stage 7).

Provides strongly-typed schemas for AST parsing, code editing,
test running, and Git operations.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FunctionInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    docstring: str | None = None
    args: list[str] = Field(default_factory=list)
    is_async: bool = False
    return_type: str | None = None
    start_line: int = 1
    end_line: int = 1


class ClassInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    docstring: str | None = None
    bases: list[str] = Field(default_factory=list)
    methods: list[FunctionInfo] = Field(default_factory=list)
    start_line: int = 1
    end_line: int = 1


class FileAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    language: str
    classes: list[ClassInfo] = Field(default_factory=list)
    functions: list[FunctionInfo] = Field(default_factory=list)
    imports: list[str] = Field(default_factory=list)
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0


class RepoAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    root_dir: str
    total_files: int = 0
    total_lines: int = 0
    languages: dict[str, int] = Field(default_factory=dict)
    files: list[FileAnalysis] = Field(default_factory=list)
    symbols: dict[str, list[str]] = Field(default_factory=dict)


class FileEdit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str
    new_content: str | None = None
    patch: str | None = None


class EditResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    modified_files: list[str] = Field(default_factory=list)
    diff: str = ""
    success: bool = True
    error: str | None = None


class TestRunResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    test_type: str
    passed: int = 0
    failed: int = 0
    errors: int = 0
    duration_sec: float = 0.0
    success: bool = True
    output: str = ""
    command: str = ""


class GitStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")
    branch: str = "main"
    clean: bool = True
    untracked: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    staged: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)


class GitResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    success: bool = True
    output: str = ""
    branch: str | None = None
    commit_hash: str | None = None
    error: str | None = None
