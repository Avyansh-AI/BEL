"""Stage 7: BEL Code — Advanced Software Engineering Agent.

Extends BEL's existing CodeAgent with:
- Multi-language repository architecture inspection
- Automated code review & static security vulnerability scanning
- Persistent development sessions
- Multi-provider coding model registry (Groq, Token Harbor, OpenRouter, OpenAI, Anthropic, Ollama)
- Build-system integration, project packaging, and autonomous diagnose-and-verify loop
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import time
import uuid
import zipfile
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from .code_agent.models import EditResult, FileEdit, TestRunResult
from .code_agent.orchestrator import CodeAgent


class CodingProviderSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")
    provider_id: str  # groq, tokenharbor, openrouter, openai, anthropic, ollama
    endpoint: str
    model: str
    auth_configured: bool = False
    pricing_verified: bool = False
    available: bool = False


class SecurityFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")
    file: str
    line: int
    severity: str  # high, medium, low
    rule: str
    snippet: str


class CodeReviewReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    files_reviewed: int
    findings: list[SecurityFinding] = Field(default_factory=list)
    passed: bool = True
    summary: str = ""


class RepoArchitectureSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")
    root: str
    languages: dict[str, int] = Field(default_factory=dict)
    build_systems: list[str] = Field(default_factory=list)
    total_files: int = 0
    test_files: list[str] = Field(default_factory=list)


class DevelopmentSession(BaseModel):
    model_config = ConfigDict(extra="ignore")
    session_id: str = Field(default_factory=lambda: f"dev-{uuid.uuid4().hex[:10]}")
    workspace_root: str
    goal: str
    plan: list[str] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    test_passed: bool = False
    review_passed: bool = False
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class BELCodeAgent:
    """Comprehensive software engineering agent built on top of CodeAgent."""

    LANGUAGE_EXTS = {
        ".py": "Python",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".rs": "Rust",
        ".go": "Go",
        ".cpp": "C++",
        ".hpp": "C++",
        ".cs": "C#",
        ".gd": "GDScript",
    }

    VULN_RULES: list[tuple[str, str, str]] = [
        ("high", "unsafe_eval", r"\beval\s*\("),
        ("high", "unsafe_exec", r"\bexec\s*\("),
        ("high", "shell_injection", r"subprocess\.\w+\(.*shell\s*=\s*True"),
        ("high", "unsafe_pickle", r"\bpickle\.loads\s*\("),
        ("medium", "hardcoded_secret", r"(?i)(api_key|secret_key|password)\s*=\s*['\"][^'\"]{8,}['\"]"),
    ]

    def __init__(self, workspace_root: Path | str, *, session_dir: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.code_agent = CodeAgent(self.workspace_root)
        self.session_dir = Path(session_dir).resolve() if session_dir else (self.workspace_root / ".bel_sessions")
        self.providers: dict[str, CodingProviderSpec] = {
            "groq": CodingProviderSpec(provider_id="groq", endpoint="https://api.groq.com/openai/v1", model="llama-3.3-70b-versatile"),
            "tokenharbor": CodingProviderSpec(provider_id="tokenharbor", endpoint="https://api.tokenharbor.com/v1", model="default"),
            "openrouter": CodingProviderSpec(provider_id="openrouter", endpoint="https://openrouter.ai/api/v1", model="qwen/qwen-2.5-coder-32b-instruct:free"),
            "openai": CodingProviderSpec(provider_id="openai", endpoint="https://api.openai.com/v1", model="gpt-4.1"),
            "anthropic": CodingProviderSpec(provider_id="anthropic", endpoint="https://api.anthropic.com/v1", model="claude-sonnet-4"),
            "ollama": CodingProviderSpec(provider_id="ollama", endpoint="http://127.0.0.1:11434", model="gemma4:e4b-it-qat"),
        }

    def inspect_repository(self) -> RepoArchitectureSummary:
        langs: dict[str, int] = {}
        builds: list[str] = []
        tests: list[str] = []
        total = 0

        build_markers = {"pyproject.toml", "package.json", "Cargo.toml", "go.mod", "CMakeLists.txt", "Makefile"}
        ignore_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".bel_sessions"}

        for p in self.workspace_root.rglob("*"):
            if any(part in ignore_dirs for part in p.parts):
                continue
            if p.is_file():
                total += 1
                if p.name in build_markers:
                    builds.append(p.name)
                if "test" in p.name.lower() and p.suffix in (".py", ".ts", ".js"):
                    tests.append(str(p.relative_to(self.workspace_root)).replace("\\", "/"))
                lang = self.LANGUAGE_EXTS.get(p.suffix.lower())
                if lang:
                    langs[lang] = langs.get(lang, 0) + 1

        return RepoArchitectureSummary(
            root=str(self.workspace_root),
            languages=langs,
            build_systems=sorted(set(builds)),
            total_files=total,
            test_files=sorted(tests),
        )

    def _resolve_workspace_path(self, rel_path: str) -> Path:
        raw = Path(rel_path)
        resolved = raw.resolve() if raw.is_absolute() else (self.workspace_root / raw).resolve()
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PermissionError(f"Path '{rel_path}' escapes workspace '{self.workspace_root}'") from exc
        return resolved

    def _safe_session_path(self, session_id: str) -> Path:
        clean = (session_id or "").strip()
        if not clean or "/" in clean or "\\" in clean or ".." in clean or ":" in clean:
            raise PermissionError(f"Invalid session_id: {session_id}")
        self.session_dir.mkdir(parents=True, exist_ok=True)
        path = (self.session_dir / f"{clean}.json").resolve()
        try:
            path.relative_to(self.session_dir.resolve())
        except ValueError as exc:
            raise PermissionError(f"Session path escapes session_dir: {session_id}") from exc
        return path

    def scan_vulnerabilities(self, rel_paths: list[str] | None = None) -> CodeReviewReport:
        targets: list[Path] = []
        if rel_paths:
            targets = [self._resolve_workspace_path(rp) for rp in rel_paths]
        else:
            for p in self.workspace_root.rglob("*"):
                if p.is_file() and p.suffix.lower() in self.LANGUAGE_EXTS:
                    if not any(part in (".git", ".venv", "node_modules", "__pycache__") for part in p.parts):
                        targets.append(p)

        findings: list[SecurityFinding] = []
        for path in targets:
            if not path.exists():
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            rel = str(path.relative_to(self.workspace_root)).replace("\\", "/")
            for idx, line in enumerate(lines, start=1):
                for sev, rule, pattern in self.VULN_RULES:
                    if re.search(pattern, line):
                        findings.append(
                            SecurityFinding(
                                file=rel,
                                line=idx,
                                severity=sev,
                                rule=rule,
                                snippet=line.strip()[:120],
                            )
                        )

        high_count = sum(1 for f in findings if f.severity == "high")
        return CodeReviewReport(
            files_reviewed=len(targets),
            findings=findings,
            passed=high_count == 0,
            summary=f"Reviewed {len(targets)} file(s): {len(findings)} finding(s) ({high_count} high severity).",
        )

    def save_session(self, session: DevelopmentSession) -> Path:
        out = self._safe_session_path(session.session_id)
        session.updated_at = time.time()
        out.write_text(session.model_dump_json(indent=2), encoding="utf-8")
        return out

    def load_session(self, session_id: str) -> DevelopmentSession:
        path = self._safe_session_path(session_id)
        if not path.exists():
            raise FileNotFoundError(f"Development session not found: {session_id}")
        return DevelopmentSession.model_validate_json(path.read_text(encoding="utf-8"))

    def list_sessions(self) -> list[str]:
        if not self.session_dir.exists():
            return []
        return sorted(p.stem for p in self.session_dir.glob("*.json"))

    def package_project(self, output_zip: Path | str) -> Path:
        out = Path(output_zip).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        ignore_dirs = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".bel_sessions"}
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in self.workspace_root.rglob("*"):
                if p.is_file() and not any(part in ignore_dirs for part in p.parts):
                    if p.resolve() == out:
                        continue
                    rel = str(p.relative_to(self.workspace_root)).replace("\\", "/")
                    zf.write(p, arcname=rel)
        return out

    def deliver_feature(
        self,
        goal: str,
        edits: list[FileEdit],
        *,
        run_pytest: bool = True,
        fix_callback: Callable[[TestRunResult], list[FileEdit]] | None = None,
    ) -> tuple[DevelopmentSession, TestRunResult | None, CodeReviewReport]:
        """End-to-end BEL Code workflow: inspect -> plan -> edit -> test -> fix -> review."""
        arch = self.inspect_repository()
        session = DevelopmentSession(
            workspace_root=str(self.workspace_root),
            goal=goal,
            plan=[
                f"Inspect repository ({arch.total_files} files)",
                f"Apply {len(edits)} file edit(s)",
                "Run test suite & diagnose failures",
                "Perform security & code review",
            ],
        )

        edit_res: EditResult = self.code_agent.apply_edits(edits)
        if not edit_res.success:
            self.save_session(session)
            return session, None, CodeReviewReport(files_reviewed=0, passed=False, summary=f"Edit failed: {edit_res.error}")

        session.modified_files = [e.path for e in edits]
        test_res: TestRunResult | None = None
        if run_pytest:
            test_res = self.code_agent.run_tests(test_type="pytest")
            if not test_res.success and fix_callback is not None:
                fix_edits = fix_callback(test_res)
                if fix_edits:
                    self.code_agent.apply_edits(fix_edits)
                    test_res = self.code_agent.run_tests(test_type="pytest")
            session.test_passed = bool(test_res.success)
        else:
            session.test_passed = True

        review = self.scan_vulnerabilities(session.modified_files)
        session.review_passed = review.passed
        self.save_session(session)
        return session, test_res, review
