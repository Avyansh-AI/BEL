"""Safe Git Automation Agent for BEL (Stage 7).

Manages branches, diff inspection, atomic conventional commits, and stash
checkpoints with strict safeguards against destructive git operations.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

from .models import GitResult, GitStatus


CONVENTIONAL_COMMIT_REGEX = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)"
    r"(\([a-zA-Z0-9_\-\.\s]+\))?: .+$"
)

VALID_BRANCH_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.\/]+$")

PROHIBITED_GIT_FLAGS = {
    "--hard",
    "-f",
    "--force",
    "--delete",
}


class GitAgent:
    """Provides safe git repository operations with guardrails."""

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self._git_bin = shutil.which("git")

    def is_git_available(self) -> bool:
        return self._git_bin is not None

    def _run_git(self, repo_dir: Path | str, args: list[str], timeout: int = 30) -> tuple[int, str, str]:
        if not self.is_git_available():
            raise RuntimeError("Git executable is not installed or not in PATH")

        repo_path = Path(repo_dir).resolve()

        # Guard against prohibited flags
        for arg in args:
            if arg.lower() in PROHIBITED_GIT_FLAGS:
                raise PermissionError(f"Prohibited git flag detected: '{arg}'")

        proc = subprocess.run(
            ["git"] + args,
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def is_repo(self, repo_dir: Path | str) -> bool:
        if not self.is_git_available():
            return False
        try:
            code, out, _ = self._run_git(repo_dir, ["rev-parse", "--is-inside-work-tree"])
            return code == 0 and out == "true"
        except Exception:
            return False

    def status(self, repo_dir: Path | str) -> GitStatus:
        if not self.is_repo(repo_dir):
            return GitStatus(branch="unknown", clean=True)

        # Get branch
        _, branch, _ = self._run_git(repo_dir, ["branch", "--show-current"])
        if not branch:
            _, branch, _ = self._run_git(repo_dir, ["rev-parse", "--short", "HEAD"])

        # Get status porcelain
        _, out, _ = self._run_git(repo_dir, ["status", "--porcelain=v1"])

        untracked: list[str] = []
        modified: list[str] = []
        staged: list[str] = []
        deleted: list[str] = []

        for line in out.splitlines():
            if len(line) < 4:
                continue
            index_status = line[0]
            work_status = line[1]
            file_name = line[3:].strip()

            if line.startswith("??"):
                untracked.append(file_name)
            else:
                if index_status in ("M", "A", "R"):
                    staged.append(file_name)
                if index_status == "D":
                    deleted.append(file_name)
                if work_status == "M":
                    modified.append(file_name)
                if work_status == "D":
                    deleted.append(file_name)

        clean = not (untracked or modified or staged or deleted)
        return GitStatus(
            branch=branch or "main",
            clean=clean,
            untracked=sorted(list(set(untracked))),
            modified=sorted(list(set(modified))),
            staged=sorted(list(set(staged))),
            deleted=sorted(list(set(deleted))),
        )

    def create_branch(self, repo_dir: Path | str, branch_name: str) -> GitResult:
        if not VALID_BRANCH_REGEX.match(branch_name) or branch_name.startswith("-"):
            return GitResult(
                success=False,
                error=f"Invalid branch name format: '{branch_name}'",
            )

        code, out, err = self._run_git(repo_dir, ["checkout", "-b", branch_name])
        if code != 0:
            return GitResult(success=False, output=out, error=err or "Branch creation failed")

        return GitResult(success=True, output=out, branch=branch_name)

    def get_diff(self, repo_dir: Path | str, staged: bool = False, file_path: str | None = None) -> str:
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file_path:
            args.extend(["--", file_path])

        _, out, _ = self._run_git(repo_dir, args)
        return out

    def stash_save(self, repo_dir: Path | str, message: str = "") -> str:
        args = ["stash", "push"]
        if message:
            args.extend(["-m", message])
        code, out, err = self._run_git(repo_dir, args)
        if code != 0:
            raise RuntimeError(f"Git stash failed: {err}")
        return out

    def stash_pop(self, repo_dir: Path | str) -> bool:
        code, _, _ = self._run_git(repo_dir, ["stash", "pop"])
        return code == 0

    def create_commit(
        self,
        repo_dir: Path | str,
        message: str,
        paths: list[str] | None = None,
        conventional: bool = True,
    ) -> GitResult:
        if conventional and not CONVENTIONAL_COMMIT_REGEX.match(message):
            return GitResult(
                success=False,
                error=(
                    "Commit message does not adhere to Conventional Commits format "
                    "(e.g. 'feat(core): add feature' or 'fix: resolve bug')."
                ),
            )

        # Stage files
        if paths:
            for p in paths:
                code, _, err = self._run_git(repo_dir, ["add", p])
                if code != 0:
                    return GitResult(success=False, error=f"Failed to stage '{p}': {err}")
        else:
            code, _, err = self._run_git(repo_dir, ["add", "-A"])
            if code != 0:
                return GitResult(success=False, error=f"Failed to stage changes: {err}")

        # Check if there is anything to commit
        code, out, _ = self._run_git(repo_dir, ["diff", "--cached", "--quiet"])
        if code == 0:
            return GitResult(success=False, error="No staged changes to commit")

        # Commit
        code, out, err = self._run_git(repo_dir, ["commit", "-m", message])
        if code != 0:
            return GitResult(success=False, output=out, error=err or "Commit execution failed")

        # Get hash
        _, commit_hash, _ = self._run_git(repo_dir, ["rev-parse", "HEAD"])
        return GitResult(
            success=True,
            output=out,
            commit_hash=commit_hash[:10] if commit_hash else None,
        )
