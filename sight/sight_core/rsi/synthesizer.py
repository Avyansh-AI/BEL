"""Forge Master / Autonomous Tool Synthesizer for BEL RSI Subsystem.

Synthesizes executable Python tools, generates accompanying unit test cases,
performs AST safety audits, and executes tests in isolated sandboxes.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any

from .boundaries import audit_code_safety
from .types import CandidateSkill, CapabilityGap, TestCase, TestExecutionResult


class ToolSynthesizer:
    """Synthesizes verified Python tools with automated test generation and sandbox testing."""

    def __init__(self, router=None) -> None:
        self.router = router

    def synthesize_tool_template(
        self,
        gap: CapabilityGap,
        custom_code: str | None = None,
        custom_tests: list[TestCase] | None = None,
    ) -> CandidateSkill:
        """Synthesize a CandidateSkill from a detected capability gap."""
        tool_id = gap.suggested_tool_name.lower().replace("-", "_")
        if not tool_id.startswith("skill_"):
            tool_id = f"skill_{tool_id}"

        # If custom code/tests provided (e.g. from LLM router or test fixture), use them
        if custom_code and custom_tests:
            code = custom_code
            tests = custom_tests
        else:
            # Deterministic standard library template generation
            code, tests = self._generate_builtin_template(gap.suggested_tool_name, gap.missing_capability)

        # 1. Audit AST Safety
        is_safe, error = audit_code_safety(code)
        if not is_safe:
            raise ValueError(f"Security Audit Rejected Code: {error}")

        # 2. Compute canonical digest
        payload = f"{tool_id}:{code}:" + json.dumps([t.model_dump() for t in tests], sort_keys=True)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        return CandidateSkill(
            id=tool_id[:79],
            name=gap.suggested_tool_name,
            description=gap.missing_capability,
            code=code,
            test_cases=tests,
            digest=digest,
            version=1,
            created_at=time.time(),
            project_id=gap.context.get("project_id", "default"),
        )

    def run_tests(
        self,
        skill: CandidateSkill,
        timeout_seconds: float = 3.0,
    ) -> TestExecutionResult:
        """Execute test cases against the candidate in an isolated subprocess sandbox."""
        start_time = time.time()

        # Build runner script
        runner_script = f"""import json
import sys

# Synthesized Tool Code
{skill.code}

# Test Execution Harness
test_cases = {repr([t.model_dump() for t in skill.test_cases])}
results = []
all_passed = True

for case in test_cases:
    name = case['name']
    inp = case['input_data']
    expected = case['expected_output']
    try:
        # Find entrypoint function (first function defined in code)
        actual = execute_tool(**inp)
        passed = (actual == expected)
        if not passed:
            all_passed = False
        results.append({{'name': name, 'passed': passed, 'actual': actual, 'expected': expected}})
    except Exception as exc:
        all_passed = False
        results.append({{'name': name, 'passed': False, 'error': str(exc), 'expected': expected}})

output = {{
    'passed': all_passed,
    'total': len(test_cases),
    'passed_count': sum(1 for r in results if r.get('passed')),
    'failed_count': sum(1 for r in results if not r.get('passed')),
    'details': results
}}
print(json.dumps(output))
"""

        with tempfile.TemporaryDirectory(prefix="bel-rsi-") as temp_dir:
            script_path = os.path.join(temp_dir, "harness.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(runner_script)

            try:
                proc = subprocess.run(
                    [sys.executable, "-I", script_path],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=timeout_seconds,
                    cwd=temp_dir,
                    env={
                        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:/Windows"),
                        "PYTHONUTF8": "1",
                        "PYTHONPATH": temp_dir,
                    },
                    shell=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )

                elapsed_ms = (time.time() - start_time) * 1000.0

                if proc.returncode != 0:
                    return TestExecutionResult(
                        passed=False,
                        total_cases=len(skill.test_cases),
                        passed_cases=0,
                        failed_cases=len(skill.test_cases),
                        execution_time_ms=elapsed_ms,
                        error_message=f"Harness process crashed (code {proc.returncode}): {proc.stderr[:300]}",
                    )

                parsed = json.loads(proc.stdout.strip())
                return TestExecutionResult(
                    passed=parsed.get("passed", False),
                    total_cases=parsed.get("total", len(skill.test_cases)),
                    passed_cases=parsed.get("passed_count", 0),
                    failed_cases=parsed.get("failed_count", 0),
                    case_details=parsed.get("details", []),
                    execution_time_ms=elapsed_ms,
                )

            except subprocess.TimeoutExpired:
                return TestExecutionResult(
                    passed=False,
                    total_cases=len(skill.test_cases),
                    passed_cases=0,
                    failed_cases=len(skill.test_cases),
                    execution_time_ms=timeout_seconds * 1000.0,
                    error_message=f"Execution timed out after {timeout_seconds}s.",
                )
            except Exception as exc:
                return TestExecutionResult(
                    passed=False,
                    total_cases=len(skill.test_cases),
                    passed_cases=0,
                    failed_cases=len(skill.test_cases),
                    error_message=f"Test runner error: {exc}",
                )

    @staticmethod
    def _generate_builtin_template(
        tool_name: str, description: str
    ) -> tuple[str, list[TestCase]]:
        """Generate verified standard-library implementations for recognized gaps."""
        t_low = tool_name.lower()

        if "celsius" in t_low or "fahrenheit" in t_low or "temperature" in t_low:
            code = '''def execute_tool(value: float, from_unit: str, to_unit: str) -> float:
    """Convert temperatures between Celsius, Fahrenheit, and Kelvin."""
    u_from = from_unit.upper().strip()
    u_to = to_unit.upper().strip()
    
    # Normalize to Celsius
    if u_from == 'C':
        c = value
    elif u_from == 'F':
        c = (value - 32.0) * 5.0 / 9.0
    elif u_from == 'K':
        c = value - 273.15
    else:
        raise ValueError(f"Unknown unit '{from_unit}'")

    # Convert from Celsius to target
    if u_to == 'C':
        return round(c, 2)
    elif u_to == 'F':
        return round(c * 9.0 / 5.0 + 32.0, 2)
    elif u_to == 'K':
        return round(c + 273.15, 2)
    else:
        raise ValueError(f"Unknown unit '{to_unit}'")
'''
            tests = [
                TestCase(
                    name="Celsius to Fahrenheit (Boiling)",
                    input_data={"value": 100.0, "from_unit": "C", "to_unit": "F"},
                    expected_output=212.0,
                ),
                TestCase(
                    name="Fahrenheit to Celsius (Freezing)",
                    input_data={"value": 32.0, "from_unit": "F", "to_unit": "C"},
                    expected_output=0.0,
                ),
                TestCase(
                    name="Celsius to Kelvin (Absolute Zero Reference)",
                    input_data={"value": 0.0, "from_unit": "C", "to_unit": "K"},
                    expected_output=273.15,
                ),
            ]
            return code, tests

        elif "hash" in t_low or "checksum" in t_low:
            code = '''import hashlib

def execute_tool(text: str, algorithm: str = "sha256") -> str:
    """Compute cryptographic hash digest for a string."""
    algo = algorithm.lower().strip()
    data = text.encode("utf-8")
    if algo == "sha256":
        return hashlib.sha256(data).hexdigest()
    elif algo == "md5":
        return hashlib.md5(data).hexdigest()
    elif algo == "sha1":
        return hashlib.sha1(data).hexdigest()
    else:
        raise ValueError(f"Unsupported algorithm '{algorithm}'")
'''
            tests = [
                TestCase(
                    name="SHA256 Empty String",
                    input_data={"text": "", "algorithm": "sha256"},
                    expected_output="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                ),
                TestCase(
                    name="MD5 Test String",
                    input_data={"text": "hello", "algorithm": "md5"},
                    expected_output="5d41402abc4b2a76b9719d911017c592",
                ),
            ]
            return code, tests

        elif "table" in t_low or "markdown" in t_low:
            code = '''def execute_tool(markdown_table: str) -> list[dict]:
    """Parse a Markdown table into a list of row dictionaries."""
    lines = [line.strip() for line in markdown_table.strip().split('\\n') if line.strip()]
    if len(lines) < 2:
        return []

    def split_row(line):
        return [cell.strip() for cell in line.strip('|').split('|')]

    headers = split_row(lines[0])
    rows = []
    # Skip separator row (line 1)
    for line in lines[2:]:
        cells = split_row(line)
        if len(cells) == len(headers):
            rows.append({h: c for h, c in zip(headers, cells)})
    return rows
'''
            sample_table = "| Name | Role |\n|---|---|\n| Tony | Executive |\n| Jarvis | AI |"
            tests = [
                TestCase(
                    name="Basic Table Parsing",
                    input_data={"markdown_table": sample_table},
                    expected_output=[
                        {"Name": "Tony", "Role": "Executive"},
                        {"Name": "Jarvis", "Role": "AI"},
                    ],
                )
            ]
            return code, tests

        else:
            # Generic string formatting utility
            code = '''def execute_tool(text: str, mode: str = "title") -> str:
    """Format input string according to specified mode."""
    m = mode.lower().strip()
    if m == "title":
        return text.title()
    elif m == "upper":
        return text.upper()
    elif m == "lower":
        return text.lower()
    else:
        return text.strip()
'''
            tests = [
                TestCase(
                    name="Title Case Test",
                    input_data={"text": "iron man", "mode": "title"},
                    expected_output="Iron Man",
                ),
                TestCase(
                    name="Upper Case Test",
                    input_data={"text": "jarvis", "mode": "upper"},
                    expected_output="JARVIS",
                ),
            ]
            return code, tests
