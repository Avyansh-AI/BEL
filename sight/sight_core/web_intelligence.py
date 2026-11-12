"""Stage 6: Web Intelligence & External Integrations for BEL.

Provides:
- Multi-source web research with credibility scoring, citations, contradiction
  detection, fact-vs-assumption separation, structured extraction, and report generation
- Extensible, permission-gated External Integration Hub (GitHub, Gmail,
  Google Calendar, REST APIs, Webhooks, Local Network Services) with fault isolation
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str
    title: str
    snippet: str
    domain: str = ""
    credibility_score: float = 0.5
    credibility_tier: str = "standard"
    fetched_at: float = Field(default_factory=time.time)


class FactClaim(BaseModel):
    model_config = ConfigDict(extra="ignore")
    statement: str
    kind: str = "fact"  # fact | assumption
    sources: list[str] = Field(default_factory=list)
    verified: bool = False


class Contradiction(BaseModel):
    model_config = ConfigDict(extra="ignore")
    topic: str
    source_a: str
    claim_a: str
    source_b: str
    claim_b: str


class ResearchReport(BaseModel):
    model_config = ConfigDict(extra="ignore")
    query: str
    sources: list[SourceDocument] = Field(default_factory=list)
    claims: list[FactClaim] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    structured_data: dict[str, Any] = Field(default_factory=dict)
    markdown_report: str = ""


class ConnectorPermission(BaseModel):
    model_config = ConfigDict(extra="ignore")
    connector_id: str
    enabled: bool = False
    allowed_scopes: list[str] = Field(default_factory=list)
    require_approval_for_write: bool = True


class ConnectorResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    connector_id: str
    scope: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class SourceCredibilityAssessor:
    """Scores source credibility based on domain authority and HTTPS."""

    HIGH_TRUST_TLDS = (".gov", ".edu", ".mil")
    REPUTABLE_DOMAINS = frozenset({
        "github.com", "docs.python.org", "developer.mozilla.org",
        "arxiv.org", "wikipedia.org", "nist.gov", "ietf.org",
    })

    def score(self, url: str) -> tuple[float, str, str]:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().lstrip("www.")
        score = 0.5
        if parsed.scheme == "https":
            score += 0.1
        if any(domain.endswith(tld) for tld in self.HIGH_TRUST_TLDS):
            score += 0.35
            tier = "high"
        elif domain in self.REPUTABLE_DOMAINS or any(domain.endswith("." + d) for d in self.REPUTABLE_DOMAINS):
            score += 0.3
            tier = "high"
        elif domain:
            tier = "standard"
        else:
            score = 0.2
            tier = "low"
        return round(min(1.0, score), 2), tier, domain


class WebResearchEngine:
    """Conducts multi-source research, verifies claims, and tracks source memory."""

    def __init__(
        self,
        *,
        search_fn: Callable[[str], list[dict[str, str]] | Awaitable[list[dict[str, str]]]] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._search_fn = search_fn
        self._transport = transport
        self._assessor = SourceCredibilityAssessor()
        self._source_memory: dict[str, SourceDocument] = {}

    @staticmethod
    def is_safe_url(url: str) -> bool:
        """Reject non-HTTP(S) schemes and SSRF private/loopback/metadata targets."""
        import ipaddress
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower()
        if not host or host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "169.254.169.254"):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False
        except ValueError:
            pass
        return True

    async def search(self, query: str) -> list[SourceDocument]:
        raw_results: list[dict[str, str]] = []
        if self._search_fn is not None:
            res = self._search_fn(query)
            if asyncio.iscoroutine(res) or isinstance(res, Awaitable):
                res = await res
            raw_results = list(res)
        else:
            # Live DuckDuckGo instant answer API fallback
            async with httpx.AsyncClient(timeout=8.0, transport=self._transport) as client:
                try:
                    resp = await client.get(
                        "https://api.duckduckgo.com/",
                        params={"q": query, "format": "json", "no_html": "1"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("AbstractURL") and data.get("AbstractText"):
                            raw_results.append({
                                "url": data["AbstractURL"],
                                "title": data.get("Heading", query),
                                "snippet": data["AbstractText"],
                            })
                except Exception:
                    pass

        docs: list[SourceDocument] = []
        for item in raw_results:
            url = item.get("url", "")
            if url and not self.is_safe_url(url):
                continue
            score, tier, domain = self._assessor.score(url)
            doc = SourceDocument(
                url=url,
                title=item.get("title", "Untitled"),
                snippet=item.get("snippet", ""),
                domain=domain,
                credibility_score=score,
                credibility_tier=tier,
            )
            docs.append(doc)
            if url:
                self._source_memory[url] = doc
        return docs

    @staticmethod
    def detect_contradictions(sources: list[SourceDocument]) -> list[Contradiction]:
        """Detect simple numeric or polarity contradictions across sources."""
        contradictions: list[Contradiction] = []
        num_pattern = re.compile(r"\b(\d+(?:\.\d+)?)\b")
        neg_words = ("not ", "never ", "false", "no ", "deprecated", "unsupported")

        for i in range(len(sources)):
            for j in range(i + 1, len(sources)):
                a, b = sources[i], sources[j]
                sa, sb = a.snippet.lower(), b.snippet.lower()
                nums_a = set(num_pattern.findall(sa))
                nums_b = set(num_pattern.findall(sb))
                if nums_a and nums_b and nums_a.isdisjoint(nums_b):
                    contradictions.append(
                        Contradiction(
                            topic="numeric_mismatch",
                            source_a=a.url,
                            claim_a=a.snippet[:160],
                            source_b=b.url,
                            claim_b=b.snippet[:160],
                        )
                    )
                elif any(w in sa for w in neg_words) != any(w in sb for w in neg_words):
                    contradictions.append(
                        Contradiction(
                            topic="polarity_mismatch",
                            source_a=a.url,
                            claim_a=a.snippet[:160],
                            source_b=b.url,
                            claim_b=b.snippet[:160],
                        )
                    )
        return contradictions

    @staticmethod
    def extract_structured_data(text: str) -> dict[str, Any]:
        emails = sorted(set(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)))
        urls = sorted(set(re.findall(r"https?://[^\s)\"']+", text)))
        numbers = re.findall(r"\b\d+(?:\.\d+)?\b", text)
        return {"emails": emails, "urls": urls, "numbers": numbers[:20]}

    async def research(self, query: str, *, assumptions: list[str] | None = None) -> ResearchReport:
        sources = await self.search(query)
        claims: list[FactClaim] = []
        for s in sources:
            if s.snippet.strip():
                claims.append(
                    FactClaim(
                        statement=s.snippet.strip(),
                        kind="fact",
                        sources=[s.url],
                        verified=s.credibility_score >= 0.6,
                    )
                )
        for asm in assumptions or []:
            claims.append(FactClaim(statement=asm, kind="assumption", sources=[], verified=False))

        contradictions = self.detect_contradictions(sources)
        combined_text = "\n".join(s.snippet for s in sources)
        structured = self.extract_structured_data(combined_text)

        lines = [f"# Research Report: {query}", "", "## Verified Facts & Citations"]
        for idx, c in enumerate(claims, start=1):
            tag = "[FACT]" if c.kind == "fact" else "[ASSUMPTION]"
            cite = f" (Sources: {', '.join(c.sources)})" if c.sources else " (Unverified)"
            lines.append(f"{idx}. {tag} {c.statement}{cite}")
        if contradictions:
            lines.extend(["", "## Contradictions Detected"])
            for con in contradictions:
                lines.append(f"- **{con.topic}**: `{con.source_a}` vs `{con.source_b}`")

        return ResearchReport(
            query=query,
            sources=sources,
            claims=claims,
            contradictions=contradictions,
            structured_data=structured,
            markdown_report="\n".join(lines),
        )

    def tracked_sources(self) -> list[SourceDocument]:
        return list(self._source_memory.values())


ConnectorHandler = Callable[[str, dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]


class IntegrationHub:
    """Permission-gated, fault-isolated hub for external services and plugins."""

    def __init__(self) -> None:
        self._permissions: dict[str, ConnectorPermission] = {}
        self._handlers: dict[str, ConnectorHandler] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        for cid in ("gmail", "google_calendar", "github", "rest_api", "webhook", "local_network"):
            self._permissions[cid] = ConnectorPermission(connector_id=cid, enabled=False, allowed_scopes=["read"])

    def configure_permission(self, perm: ConnectorPermission) -> None:
        self._permissions[perm.connector_id] = perm

    def register_connector(self, connector_id: str, handler: ConnectorHandler, permission: ConnectorPermission | None = None) -> None:
        self._handlers[connector_id] = handler
        if permission is not None:
            self._permissions[connector_id] = permission
        elif connector_id not in self._permissions:
            self._permissions[connector_id] = ConnectorPermission(connector_id=connector_id, enabled=False)

    def list_permissions(self) -> list[ConnectorPermission]:
        return [self._permissions[k] for k in sorted(self._permissions.keys())]

    async def invoke(
        self,
        connector_id: str,
        scope: str,
        payload: dict[str, Any] | None = None,
        *,
        approved: bool = False,
        timeout_sec: float = 15.0,
    ) -> ConnectorResult:
        perm = self._permissions.get(connector_id)
        if not perm or not perm.enabled:
            return ConnectorResult(connector_id=connector_id, scope=scope, success=False, error="Connector is disabled by permission policy")
        if scope not in perm.allowed_scopes:
            return ConnectorResult(connector_id=connector_id, scope=scope, success=False, error=f"Scope '{scope}' not permitted for '{connector_id}'")
        if perm.require_approval_for_write and scope in ("write", "send", "delete", "create") and not approved:
            return ConnectorResult(connector_id=connector_id, scope=scope, success=False, error="Explicit approval required for write scope")

        handler = self._handlers.get(connector_id)
        if handler is None:
            return ConnectorResult(connector_id=connector_id, scope=scope, success=False, error=f"No handler registered for '{connector_id}'")

        try:
            res = handler(scope, payload or {})
            if asyncio.iscoroutine(res) or isinstance(res, Awaitable):
                res = await asyncio.wait_for(res, timeout=timeout_sec)
            return ConnectorResult(connector_id=connector_id, scope=scope, success=True, data=res if isinstance(res, dict) else {"result": res})
        except asyncio.TimeoutError:
            return ConnectorResult(connector_id=connector_id, scope=scope, success=False, error=f"TimeoutError: Connector '{connector_id}' exceeded {timeout_sec}s deadline")
        except Exception as exc:
            # Fault isolation: never propagate external integration failure to crash main assistant
            return ConnectorResult(connector_id=connector_id, scope=scope, success=False, error=f"{type(exc).__name__}: {exc}")
