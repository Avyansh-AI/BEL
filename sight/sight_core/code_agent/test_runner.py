"""Sandboxed Test Runner for BEL (Stage 7).

Executes test suites (pytest, npm test, cargo test) with strict timeouts,
output caps, workspace cwd containment, and structured outcome extraction.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .models import TestRunResult


MAX_OUTPUT_CHARS = 60_000


class TestRunner:
    """Safely executes test commands in subprocesses within a workspace."""

    __test__ = False

    def __init__(self, workspace_root: Path | str | None = None) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else Path.cwd().resolve()

    def run_tests(
        self,
        test_type: str = "pytest",
        target: str | None = None,
        cwd: Path | str | None = None,
        timeout_sec: int = 60,
        extra_args: list[str] | None = None,
    ) -> TestRunResult:
        """Run tests and return structured TestRunResult."""
        effective_cwd = Path(cwd).resolve() if cwd else self.workspace_root

        # Workspace containment check
        try:
            effective_cwd.relative_to(self.workspace_root)
        except ValueError:
            return TestRunResult(
                test_type=test_type,
                success=False,
                output=f"Security violation: cwd '{effective_cwd}' is outside workspace '{self.workspace_root}'",
                command="",
            )

        cmd: list[str] = []
        if test_type == "pytest":
            cmd = [sys.executable, "-m", "pytest"]
            if target:
                cmd.append(target)
            cmd.extend(["-q", "--no-header"])
        elif test_type == "npm":
            cmd = ["npm", "test", "--"]
            if target:
                cmd.append(target)
        elif test_type == "cargo":
            cmd = ["cargo", "test"]
            if target:
                cmd.extend(["--test", target])
        else:
            return TestRunResult(
                test_type=test_type,
                success=False,
                output=f"Unsupported test runner type: '{test_type}'",
                command="",
            )

        if extra_args:
            cmd.extend(extra_args)

        start_time = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(effective_cwd),
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                shell=(os.name == "nt" and test_type in ("npm", "cargo")),
            )
            duration = time.monotonic() - start_time
            raw_output = (proc.stdout + "\n" + proc.stderr).strip()
            truncated_output = raw_output[:MAX_OUTPUT_CHARS]

            passed, failed, errors = self._parse_test_counts(test_type, truncated_output, proc.returncode)
            success = proc.returncode == 0

            return TestRunResult(
                test_type=test_type,
                passed=passed,
                failed=failed,
                errors=errors,
                duration_sec=round(duration, 3),
                success=success,
                output=truncated_output,
                command=" ".join(cmd),
            )

        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start_time
            out = exc.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            return TestRunResult(
                test_type=test_type,
                passed=0,
                failed=1,
                errors=1,
                duration_sec=round(duration, 3),
                success=False,
                output=f"Test execution timed out after {timeout_sec}s.\n{out}",
                command=" ".join(cmd),
            )
        except Exception as exc:
            duration = time.monotonic() - start_time
            return TestRunResult(
                test_type=test_type,
                passed=0,
                failed=0,
                errors=1,
                duration_sec=round(duration, 3),
                success=False,
                output=f"Test execution failed to spawn: {exc}",
                command=" ".join(cmd),
            )

    def _parse_test_counts(self, test_type: str, output: str, returncode: int) -> tuple[int, int, int]:
        """Extract passed, failed, and error counts from test output."""
        passed = 0
        failed = 0
        errors = 0

        if test_type == "pytest":
            # Match patterns like: "5 passed, 1 failed, 2 errors in 0.5s"
            pass_match = re.search(r"(\d+)\s+passed", output)
            if pass_match:
                passed = int(pass_match.group(1))

            fail_match = re.search(r"(\d+)\s+failed", output)
            if fail_match:
                failed = int(fail_match.group(1))

            err_match = re.search(r"(\d+)\s+error", output)
            if err_match:
                errors = int(err_match.group(1))

            if returncode != 0 and passed == 0 and failed == 0 and errors == 0:
                failed = 1

        elif test_type == "npm":
            # Jest / Vitest patterns: Tests: 2 failed, 10 passed, 12 total
            pass_match = re.search(r"(\d+)\s+passed", output)
            if pass_match:
                passed = int(pass_match.group(1))
            fail_match = re.search(r"(\d+)\s+failed", output)
            if fail_match:
                failed = int(fail_match.group(1))
            if returncode != 0 and passed == 0 and failed == 0:
                failed = 1

        elif test_type == "cargo":
            # Cargo pattern: test result: ok. 5 passed; 0 failed; 0 ignored;
            match = re.search(r"test result: \w+\.\s+(\d+)\s+passed;\s+(\d+)\s+failed;", output)
            if match:
                passed = int(match.group(1))
                failed = int(match.group(2))
            elif returncode != 0:
                failed = 1

        return passed, failed, errors
