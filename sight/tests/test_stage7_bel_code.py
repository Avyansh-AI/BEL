"""Stage 7 Verification Tests: BEL Code Advanced Development Agent."""
from pathlib import Path
from sight_core.bel_code import BELCodeAgent
from sight_core.code_agent.models import FileEdit


def test_stage7_repo_inspection_security_scan_and_packaging(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (tmp_path / "test_app.py").write_text("from app import add\ndef test_add():\n    assert add(1, 2) == 3\n", encoding="utf-8")

    agent = BELCodeAgent(tmp_path)
    arch = agent.inspect_repository()
    assert arch.languages["Python"] == 2
    assert "pyproject.toml" in arch.build_systems
    assert "test_app.py" in arch.test_files

    # Security scan catches unsafe eval
    (tmp_path / "bad.py").write_text("x = eval('1+1')\n", encoding="utf-8")
    rev = agent.scan_vulnerabilities(["bad.py"])
    assert not rev.passed and rev.findings[0].rule == "unsafe_eval"
    (tmp_path / "bad.py").unlink()

    # Multi-file delivery + session persistence + packaging
    session, test_res, clean_rev = agent.deliver_feature(
        "Update add function",
        [FileEdit(path="app.py", new_content="def add(a, b):\n    return int(a) + int(b)\n")],
        run_pytest=False,
    )
    assert session.review_passed and clean_rev.passed
    loaded = agent.load_session(session.session_id)
    assert loaded.goal == "Update add function"

    pkg = agent.package_project(tmp_path / "dist" / "demo.zip")
    assert pkg.exists() and pkg.stat().st_size > 0
