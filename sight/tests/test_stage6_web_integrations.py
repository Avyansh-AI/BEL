"""Stage 6 Verification Tests: Web Intelligence & External Integrations."""
import asyncio

from sight_core.web_intelligence import (
    ConnectorPermission,
    IntegrationHub,
    WebResearchEngine,
)


def test_stage6_multi_source_research_contradictions_and_citations():
    def fake_search(query: str):
        return [
            {
                "url": "https://docs.python.org/3/library/asyncio.html",
                "title": "Python Asyncio Docs",
                "snippet": "Python 3.12 supports TaskGroup for structured concurrency.",
            },
            {
                "url": "https://example.com/blog/post",
                "title": "Outdated Blog",
                "snippet": "Python 3.9 does not support TaskGroup.",
            },
        ]

    engine = WebResearchEngine(search_fn=fake_search)
    report = asyncio.run(engine.research("Python TaskGroup", assumptions=["User has Python 3.12 installed"]))

    assert len(report.sources) == 2
    assert report.sources[0].credibility_tier == "high"
    assert any(c.kind == "fact" and c.sources for c in report.claims)
    assert any(c.kind == "assumption" and not c.verified for c in report.claims)
    assert len(report.contradictions) >= 1
    assert "[FACT]" in report.markdown_report and "[ASSUMPTION]" in report.markdown_report
    assert len(engine.tracked_sources()) == 2


def test_stage6_integration_hub_permissions_and_fault_isolation():
    hub = IntegrationHub()

    def github_handler(scope: str, payload: dict):
        if payload.get("crash"):
            raise ConnectionError("GitHub 503")
        return {"repo": payload.get("repo"), "scope": scope}

    hub.register_connector(
        "github",
        github_handler,
        ConnectorPermission(connector_id="github", enabled=True, allowed_scopes=["read", "write"], require_approval_for_write=True),
    )

    # Disabled connector denied
    denied = asyncio.run(hub.invoke("gmail", "read"))
    assert not denied.success and "disabled" in denied.error

    # Write scope requires approval
    unapproved = asyncio.run(hub.invoke("github", "write", {"repo": "BEL"}))
    assert not unapproved.success and "approval" in unapproved.error.lower()

    # Approved write succeeds
    ok = asyncio.run(hub.invoke("github", "write", {"repo": "BEL"}, approved=True))
    assert ok.success and ok.data["repo"] == "BEL"

    # Crash in external connector is isolated cleanly
    isolated = asyncio.run(hub.invoke("github", "read", {"crash": True}))
    assert not isolated.success and "ConnectionError" in isolated.error
