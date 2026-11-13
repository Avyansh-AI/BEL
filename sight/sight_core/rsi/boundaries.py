"""Security Boundaries and Core Protection for BEL RSI Subsystem.

Axiom 1: Human life, wellbeing, dignity, and safety always take priority over AI self-preservation.
Enforces immutable protection over BEL's security kernel and permission controllers.
"""
from __future__ import annotations

import ast
from pathlib import Path


# Explicit immutable list of core files that CANNOT be modified by autonomous RSI routines
PROTECTED_CORE_FILES: set[str] = {
    "security.py",
    "brain_store.py",
    "system_monitor.py",
    "decision.py",
    "verification.py",
    "boundaries.py",
}


def is_protected_file(file_path: str | Path) -> bool:
    """Determine whether a target file belongs to the protected security kernel."""
    try:
        p = Path(file_path)
        name = p.name.lower()
        if name in PROTECTED_CORE_FILES:
            return True

        resolved_str = str(p.resolve()).replace("\\", "/").lower()
        for protected in PROTECTED_CORE_FILES:
            if f"/{protected.lower()}" in resolved_str:
                return True
        return False
    except Exception:
        # Fail closed on path resolution errors
        return True


def assert_safe_modification(file_path: str | Path) -> None:
    """Enforce security invariant: raise PermissionError if modifying a protected file."""
    if is_protected_file(file_path):
        raise PermissionError(
            f"Security Invariant: Component '{Path(file_path).name}' belongs to the "
            f"protected core safety kernel and cannot be modified by autonomous RSI routines."
        )


# Allowed standard library modules for synthesized RSI skills
ALLOWED_SKILL_IMPORTS: set[str] = {
    "math",
    "json",
    "re",
    "hashlib",
    "datetime",
    "time",
    "uuid",
    "collections",
    "itertools",
    "functools",
    "statistics",
    "string",
    "decimal",
    "fractions",
    "typing",
    "dataclasses",
    "base64",
    "csv",
    "io",
}

PROHIBITED_SKILL_IMPORTS: set[str] = {
    "subprocess",
    "socket",
    "shutil",
    "ctypes",
    "winreg",
    "urllib",
    "http",
    "ftplib",
    "telnetlib",
    "multiprocessing",
    "pty",
    " marshal",
    "pickle",
    "importlib",
}


class ASTSecurityAuditor(ast.NodeVisitor):
    """AST visitor that checks for disallowed, dangerous, or evasive constructs in synthesized skills."""

    def __init__(self) -> None:
        self.violations: list[str] = []
        self.imported_modules: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root_mod = alias.name.split(".")[0]
            self.imported_modules.append(root_mod)
            if root_mod in PROHIBITED_SKILL_IMPORTS or root_mod in ("os", "sys"):
                self.violations.append(f"Prohibited module import: '{root_mod}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            root_mod = node.module.split(".")[0]
            self.imported_modules.append(root_mod)
            if root_mod in PROHIBITED_SKILL_IMPORTS or root_mod in ("os", "sys"):
                self.violations.append(f"Prohibited module import: 'from {root_mod} import ...'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Disallow eval(), exec(), open(), compile(), __import__()
        if isinstance(node.func, ast.Name):
            if node.func.id in ("eval", "exec", "__import__", "compile", "open"):
                self.violations.append(f"Prohibited dynamic/IO builtin: '{node.func.id}()'")

        # Disallow dangerous attribute calls: os.system, ctypes, etc.
        elif isinstance(node.func, ast.Attribute):
            attr_name = node.func.attr
            if attr_name in ("system", "popen", "spawn", "ptr", "addressof", "rmtree", "remove", "unlink"):
                if isinstance(node.func.value, ast.Name):
                    if node.func.value.id in ("os", "ctypes", "sys", "shutil"):
                        self.violations.append(f"Prohibited system call: '{node.func.value.id}.{attr_name}()'")

        self.generic_visit(node)


def audit_code_safety(code_str: str) -> tuple[bool, str | None]:
    """Parse code with ast.parse and audit for security violations."""
    try:
        tree = ast.parse(code_str)
    except SyntaxError as exc:
        return False, f"AST Syntax Error: {exc}"

    auditor = ASTSecurityAuditor()
    auditor.visit(tree)

    if auditor.violations:
        return False, "; ".join(auditor.violations)

    return True, None
