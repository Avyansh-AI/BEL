"""Codebase AST Parser and Structural Analyzer for BEL (Stage 7).

Extracts classes, functions, imports, comments, and metrics across Python,
TypeScript/JavaScript, C++, Rust, and GDScript codebases.
"""
from __future__ import annotations

import ast
from pathlib import Path
import re
from typing import Sequence

from .models import ClassInfo, FileAnalysis, FunctionInfo, RepoAnalysis


IGNORED_DIRECTORIES: set[str] = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    ".idea",
    ".vscode",
    ".cache",
    "owner-data",
}

LANGUAGE_EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript-react",
    ".js": "javascript",
    ".jsx": "javascript-react",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".rs": "rust",
    ".gd": "gdscript",
    ".json": "json",
    ".md": "markdown",
    ".tscn": "godot-scene",
}


class PythonASTVisitor(ast.NodeVisitor):
    """AST visitor extracting structural symbols from Python modules."""

    def __init__(self) -> None:
        self.classes: list[ClassInfo] = []
        self.functions: list[FunctionInfo] = []
        self.imports: list[str] = []
        self._current_class: ClassInfo | None = None

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        for alias in node.names:
            self.imports.append(f"{mod}.{alias.name}" if mod else alias.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        bases = [ast.unparse(b) for b in node.bases if hasattr(ast, "unparse")]
        class_info = ClassInfo(
            name=node.name,
            docstring=ast.get_docstring(node),
            bases=bases,
            methods=[],
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
        )
        old_class = self._current_class
        self._current_class = class_info

        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(item)

        self._current_class = old_class
        self.classes.append(class_info)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record_func(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record_func(node, is_async=True)

    def _record_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool) -> None:
        args = [arg.arg for arg in node.args.args]
        ret_type = ast.unparse(node.returns) if (node.returns and hasattr(ast, "unparse")) else None
        func_info = FunctionInfo(
            name=node.name,
            docstring=ast.get_docstring(node),
            args=args,
            is_async=is_async,
            return_type=ret_type,
            start_line=node.lineno,
            end_line=getattr(node, "end_lineno", node.lineno),
        )
        if self._current_class:
            self._current_class.methods.append(func_info)
        else:
            self.functions.append(func_info)


class CodebaseAnalyzer:
    """Multi-language static and AST analyzer for software projects."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None

    def analyze_file(self, file_path: Path | str) -> FileAnalysis:
        path = Path(file_path)
        ext = path.suffix.lower()
        language = LANGUAGE_EXTENSIONS.get(ext, "unknown")

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return FileAnalysis(path=str(path), language=language)

        lines = content.splitlines()
        total_lines = len(lines)
        blank_lines = sum(1 for line in lines if not line.strip())
        comment_lines = 0
        code_lines = 0

        # Calculate basic comment/code metrics
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("/*"):
                comment_lines += 1
            else:
                code_lines += 1

        if language == "python":
            return self._analyze_python(path, content, total_lines, code_lines, comment_lines, blank_lines)
        else:
            return self._analyze_regex_fallback(path, language, content, total_lines, code_lines, comment_lines, blank_lines)

    def _analyze_python(
        self,
        path: Path,
        content: str,
        total: int,
        code: int,
        comments: int,
        blank: int,
    ) -> FileAnalysis:
        try:
            tree = ast.parse(content, filename=str(path))
            visitor = PythonASTVisitor()
            visitor.visit(tree)
            return FileAnalysis(
                path=str(path),
                language="python",
                classes=visitor.classes,
                functions=visitor.functions,
                imports=sorted(list(set(visitor.imports))),
                total_lines=total,
                code_lines=code,
                comment_lines=comments,
                blank_lines=blank,
            )
        except SyntaxError:
            # Fall back to regex parsing on syntax errors
            return self._analyze_regex_fallback(path, "python", content, total, code, comments, blank)

    def _analyze_regex_fallback(
        self,
        path: Path,
        language: str,
        content: str,
        total: int,
        code: int,
        comments: int,
        blank: int,
    ) -> FileAnalysis:
        classes: list[ClassInfo] = []
        functions: list[FunctionInfo] = []
        imports: list[str] = []

        lines = content.splitlines()
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Class definitions
            class_match = re.match(r"^(?:export\s+)?class\s+([A-Za-z0-9_]+)", stripped)
            if class_match:
                classes.append(ClassInfo(name=class_match.group(1), start_line=i, end_line=i))
                continue

            # Function / method definitions
            func_match = re.match(
                r"^(?:async\s+)?(?:export\s+)?(?:def|function|func)\s+([A-Za-z0-9_]+)\s*\((.*?)\)",
                stripped,
            )
            if func_match:
                f_name = func_match.group(1)
                raw_args = [a.strip() for a in func_match.group(2).split(",") if a.strip()]
                is_async = "async " in stripped
                functions.append(
                    FunctionInfo(
                        name=f_name,
                        args=raw_args,
                        is_async=is_async,
                        start_line=i,
                        end_line=i,
                    )
                )
                continue

            # Imports
            imp_match = re.match(r"^(?:from\s+([A-Za-z0-9_\.]+)\s+import|import\s+([A-Za-z0-9_\.]+))", stripped)
            if imp_match:
                imports.append(imp_match.group(1) or imp_match.group(2))
                continue

            js_imp = re.match(r"^import\s+(?:\{[^}]+\}|\*\s+as\s+[A-Za-z0-9_]+|[A-Za-z0-9_]+)\s+from\s+['\"]([^'\"]+)['\"]", stripped)
            if js_imp:
                imports.append(js_imp.group(1))

        return FileAnalysis(
            path=str(path),
            language=language,
            classes=classes,
            functions=functions,
            imports=sorted(list(set(imports))),
            total_lines=total,
            code_lines=code,
            comment_lines=comments,
            blank_lines=blank,
        )

    def analyze_directory(
        self,
        directory: Path | str,
        max_files: int = 500,
        exclude_dirs: Sequence[str] | None = None,
    ) -> RepoAnalysis:
        root = Path(directory).resolve()
        exclude = set(exclude_dirs or []).union(IGNORED_DIRECTORIES)

        all_analyses: list[FileAnalysis] = []
        lang_counts: dict[str, int] = {}
        total_lines = 0
        symbols: dict[str, list[str]] = {}

        for p in root.rglob("*"):
            if len(all_analyses) >= max_files:
                break
            if p.is_dir():
                continue
            # Check exclusions
            parts = set(p.parts)
            if parts.intersection(exclude):
                continue
            if p.suffix.lower() not in LANGUAGE_EXTENSIONS:
                continue

            analysis = self.analyze_file(p)
            all_analyses.append(analysis)

            lang = analysis.language
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
            total_lines += analysis.total_lines

            # Index symbols
            rel_path = str(p.relative_to(root)).replace("\\", "/")
            for c in analysis.classes:
                symbols.setdefault(c.name, []).append(rel_path)
            for f in analysis.functions:
                symbols.setdefault(f.name, []).append(rel_path)

        return RepoAnalysis(
            root_dir=str(root),
            total_files=len(all_analyses),
            total_lines=total_lines,
            languages=lang_counts,
            files=all_analyses,
            symbols=symbols,
        )

    def find_references(self, symbol: str, directory: Path | str) -> list[str]:
        root = Path(directory).resolve()
        matches: list[str] = []
        pattern = re.compile(rf"\b{re.escape(symbol)}\b")

        for p in root.rglob("*"):
            if p.is_dir() or set(p.parts).intersection(IGNORED_DIRECTORIES):
                continue
            if p.suffix.lower() not in LANGUAGE_EXTENSIONS:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
                if pattern.search(content):
                    matches.append(str(p.relative_to(root)).replace("\\", "/"))
            except Exception:
                continue

        return matches
