"""Safe Multi-File Code Editor for BEL (Stage 7).

Enforces workspace boundary containment, protected file safety invariants,
AST security auditing, atomic rollback, and unified diff generation.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Sequence

from ..rsi.boundaries import PROTECTED_CORE_FILES, audit_code_safety, is_protected_file
from .models import EditResult, FileEdit


class SecurityBoundaryViolation(PermissionError):
    """Raised when an operation attempts to access files outside the workspace."""
    pass


class CodeEditor:
    """Safely applies file modifications and creations within a designated workspace."""

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if not self.workspace_root.exists():
            self.workspace_root.mkdir(parents=True, exist_ok=True)

    def _resolve_safe_path(self, target_path: Path | str) -> Path:
        """Resolve path and verify it is strictly within workspace_root."""
        raw = Path(target_path)
        if raw.is_absolute():
            resolved = raw.resolve()
        else:
            resolved = (self.workspace_root / raw).resolve()

        # Enforce containment
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError:
            raise SecurityBoundaryViolation(
                f"Access denied: Target path '{target_path}' is outside workspace '{self.workspace_root}'"
            )

        # Enforce protected core files
        if is_protected_file(resolved):
            raise PermissionError(
                f"Security Invariant: File '{resolved.name}' belongs to the protected "
                f"safety kernel and cannot be modified by autonomous code routines."
            )

        return resolved

    def preview_diff(self, file_path: Path | str, new_content: str) -> str:
        """Generate a unified diff between current disk content and proposed content."""
        target = self._resolve_safe_path(file_path)
        old_content = ""
        if target.exists() and target.is_file():
            try:
                old_content = target.read_text(encoding="utf-8", errors="replace")
            except Exception:
                old_content = ""

        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{target.name}",
                tofile=f"b/{target.name}",
            )
        )
        return "".join(diff_lines)

    def write_file(self, file_path: Path | str, content: str) -> EditResult:
        """Create or overwrite a file with safety and AST auditing."""
        target = self._resolve_safe_path(file_path)

        # Python files undergo AST security audit
        if target.suffix.lower() == ".py":
            safe, reason = audit_code_safety(content)
            if not safe:
                return EditResult(
                    modified_files=[],
                    diff="",
                    success=False,
                    error=f"AST Security Audit Rejected: {reason}",
                )

        diff = self.preview_diff(target, content)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        rel_path = str(target.relative_to(self.workspace_root)).replace("\\", "/")
        return EditResult(
            modified_files=[rel_path],
            diff=diff,
            success=True,
        )

    def apply_edits(self, edits: Sequence[FileEdit]) -> EditResult:
        """Atomically apply a batch of file edits with rollback on any failure."""
        if not edits:
            return EditResult(modified_files=[], diff="", success=True)

        snapshots: dict[Path, str | None] = {}
        all_diffs: list[str] = []
        modified: list[str] = []

        try:
            # Phase 1: Validation and pre-edit snapshot capture
            for edit in edits:
                target = self._resolve_safe_path(edit.path)
                if target not in snapshots:
                    snapshots[target] = (
                        target.read_text(encoding="utf-8", errors="replace")
                        if target.exists() and target.is_file()
                        else None
                    )

                new_text = edit.new_content if edit.new_content is not None else ""

                # Python AST safety validation
                if target.suffix.lower() == ".py":
                    safe, reason = audit_code_safety(new_text)
                    if not safe:
                        raise ValueError(f"Security audit failed for '{edit.path}': {reason}")

                diff = self.preview_diff(target, new_text)
                if diff:
                    all_diffs.append(diff)

            # Phase 2: Apply writes
            for edit in edits:
                target = self._resolve_safe_path(edit.path)
                new_text = edit.new_content if edit.new_content is not None else ""
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(new_text, encoding="utf-8")
                rel_path = str(target.relative_to(self.workspace_root)).replace("\\", "/")
                if rel_path not in modified:
                    modified.append(rel_path)

            return EditResult(
                modified_files=modified,
                diff="\n".join(all_diffs),
                success=True,
            )

        except Exception as exc:
            # Phase 3: Rollback on any failure
            for path, orig_content in snapshots.items():
                try:
                    if orig_content is None:
                        if path.exists():
                            path.unlink(missing_ok=True)
                    else:
                        path.write_text(orig_content, encoding="utf-8")
                except Exception:
                    pass

            return EditResult(
                modified_files=[],
                diff="",
                success=False,
                error=f"Transaction rolled back: {exc}",
            )
