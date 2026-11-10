"""Unified Hierarchical Memory Coordinator for BEL.

Orchestrates:
1. Working Memory (active context, in-flight tasks, scratchpad)
2. Short-Term Memory (session buffer, ephemeral state)
3. Long-Term Memory (persistent user preferences, verified facts)
4. Project Memory (strict isolated partitions: BEL, ADA, Badami, Octo6, etc.)
5. Semantic Memory (general technology patterns, concepts, idioms)
6. Episodic Memory (chronological execution history and tool receipts)
7. Document RAG (ingested documentation, guides, and source files)
"""
from __future__ import annotations

import time
from typing import Any

from .embeddings import DenseVectorizer
from .manager import MemoryManagementEngine
from .project_memory import ProjectMemoryService
from .rag import RAGEngine
from .types import ConflictResolution, MemoryTier, ProjectCategory, RetrievalResult
from ..memory import MemoryInput, MemoryService


class HierarchicalMemoryCoordinator:
    """Central hierarchical coordinator for all memory tiers."""

    def __init__(
        self,
        store,
        memory_service: MemoryService | None = None,
        project_memory: ProjectMemoryService | None = None,
        rag_engine: RAGEngine | None = None,
        manager: MemoryManagementEngine | None = None,
        vectorizer: DenseVectorizer | None = None,
        clock=time.time,
    ) -> None:
        self.store = store
        self.clock = clock
        self.vectorizer = vectorizer or DenseVectorizer()
        self.memory_service = memory_service or MemoryService(store, clock=clock)
        self.project_memory = project_memory or ProjectMemoryService(
            store, vectorizer=self.vectorizer, clock=clock
        )
        self.rag = rag_engine or RAGEngine(store, vectorizer=self.vectorizer, clock=clock)
        self.manager = manager or MemoryManagementEngine(
            store, vectorizer=self.vectorizer, clock=clock
        )

        # In-memory working buffer for in-flight tasks and active scratchpad
        self._working_scratchpad: dict[str, Any] = {}

    # -------------------------------------------------------------------------
    # Working Memory Management
    # -------------------------------------------------------------------------

    def set_scratchpad(self, key: str, value: Any) -> None:
        """Store transient working state for active reasoning cycles."""
        self._working_scratchpad[key] = value

    def get_scratchpad(self, key: str, default: Any = None) -> Any:
        """Retrieve working state."""
        return self._working_scratchpad.get(key, default)

    def clear_scratchpad(self) -> None:
        """Clear active scratchpad."""
        self._working_scratchpad.clear()

    # -------------------------------------------------------------------------
    # Storage & Conflict Resolution
    # -------------------------------------------------------------------------

    def remember(
        self,
        tier: MemoryTier | str,
        content: str,
        project_id: str = "default",
        key: str = "fact",
        title: str | None = None,
        category: ProjectCategory | str = ProjectCategory.DECISION,
        importance: int = 3,
        confidence: float = 1.0,
        is_explicit_correction: bool = False,
    ) -> dict[str, Any]:
        """Store knowledge in the appropriate hierarchical tier with deduplication and conflict checks."""
        t = tier if isinstance(tier, MemoryTier) else MemoryTier(tier)

        # 1. Project Memory Tier
        if t == MemoryTier.PROJECT:
            dup_id, dup_sim = self.manager.detect_duplicate(content, project_id)
            if dup_sim >= 0.95 and not is_explicit_correction:
                return {
                    "status": "duplicate_ignored",
                    "existing_id": dup_id,
                    "similarity": dup_sim,
                }

            rec = self.project_memory.add_record(
                project_id=project_id,
                category=category,
                title=title or key,
                content=content,
                importance=importance,
                confidence=confidence,
            )
            return {"status": "saved", "id": rec.id, "tier": t.value}

        # 2. Long-Term Memory Tier (User preferences & verified facts)
        elif t == MemoryTier.LONG_TERM:
            resolution = self.manager.resolve_conflict(
                new_key=key,
                new_content=content,
                project_id=project_id,
                new_confidence=confidence,
                is_explicit_correction=is_explicit_correction,
            )

            if resolution.status == "contradiction_flagged":
                return {
                    "status": "conflict_flagged",
                    "reason": resolution.reason,
                    "existing_id": resolution.existing_id,
                }

            mem_input = MemoryInput(
                store="profile",
                project_id=project_id,
                key=key,
                content=content,
                confidence=confidence,
            )
            saved = self.memory_service.put(mem_input)
            return {
                "status": "saved",
                "id": saved["id"],
                "tier": t.value,
                "conflict_resolution": resolution.status,
            }

        # 3. Document RAG Tier
        elif t == MemoryTier.DOCUMENT_RAG:
            doc = self.rag.ingest_text(
                title=title or key,
                text=content,
                project_id=project_id,
            )
            return {"status": "saved", "id": doc.id, "tier": t.value, "chunks": doc.total_chunks}

        # 4. Episodic Memory Tier
        elif t == MemoryTier.EPISODIC:
            mem_input = MemoryInput(
                store="episode",
                project_id=project_id,
                key=key,
                content=content,
                confidence=confidence,
            )
            saved = self.memory_service.put(mem_input)
            return {"status": "saved", "id": saved["id"], "tier": t.value}

        else:
            raise ValueError(f"Direct storage into tier '{t.value}' not supported via remember()")

    # -------------------------------------------------------------------------
    # Unified Retrieval Across Tiers
    # -------------------------------------------------------------------------

    def retrieve(
        self,
        query: str,
        project_id: str = "default",
        tiers: list[MemoryTier] | None = None,
        limit: int = 6,
    ) -> list[RetrievalResult]:
        """Unified multi-tier retrieval with source attribution."""
        if not query or not query.strip():
            return []

        active_tiers = tiers or [
            MemoryTier.PROJECT,
            MemoryTier.LONG_TERM,
            MemoryTier.DOCUMENT_RAG,
            MemoryTier.EPISODIC,
        ]

        results: list[RetrievalResult] = []

        # 1. Project Memory
        if MemoryTier.PROJECT in active_tiers:
            proj_hits = self.project_memory.search(project_id, query, limit=limit)
            for rec, score in proj_hits:
                results.append(
                    RetrievalResult(
                        id=rec.id,
                        tier=MemoryTier.PROJECT,
                        project_id=rec.project_id,
                        title=rec.title,
                        content=rec.content,
                        score=score,
                        source_attribution=f"[{rec.project_id}:{rec.category.value}:{rec.title}]",
                        metadata={"importance": rec.importance, "category": rec.category.value},
                    )
                )

        # 2. Document RAG
        if MemoryTier.DOCUMENT_RAG in active_tiers:
            rag_hits = self.rag.search(query, project_id=project_id, limit=limit)
            for chunk in rag_hits:
                results.append(
                    RetrievalResult(
                        id=chunk.id,
                        tier=MemoryTier.DOCUMENT_RAG,
                        project_id=chunk.project_id,
                        title=chunk.metadata.get("doc_title", "Document"),
                        content=chunk.content,
                        score=chunk.score or 0.1,
                        source_attribution=chunk.source_attribution or f"[{chunk.doc_id}:{chunk.chunk_index}]",
                        metadata=chunk.metadata,
                    )
                )

        # 3. Long-Term and Episodic Memory (MemoryService)
        if MemoryTier.LONG_TERM in active_tiers or MemoryTier.EPISODIC in active_tiers:
            mem_hits = self.memory_service.search(query, project_id=project_id, limit=limit)
            for item in mem_hits:
                tier = (
                    MemoryTier.LONG_TERM
                    if item.get("store") == "profile"
                    else MemoryTier.EPISODIC
                )
                if tier in active_tiers:
                    results.append(
                        RetrievalResult(
                            id=item["id"],
                            tier=tier,
                            project_id=item["project_id"],
                            title=item["key"],
                            content=item["content"],
                            score=0.2,
                            source_attribution=f"[{tier.value}:{item['key']}]",
                            metadata={"revision": item.get("revision", 1)},
                        )
                    )

        # Sort all results by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    # -------------------------------------------------------------------------
    # Context Synthesis for Orchestration
    # -------------------------------------------------------------------------

    def synthesize_context(
        self,
        query: str,
        project_id: str = "default",
        max_bytes: int = 1500,
    ) -> dict[str, Any]:
        """Synthesize a structured markdown context block for LLM prompts."""
        hits = self.retrieve(query, project_id=project_id, limit=6)
        if not hits:
            return {"context_text": "", "citations": []}

        sections: list[str] = ["=== RETRIEVED MEMORY & KNOWLEDGE ==="]
        citations: list[dict[str, Any]] = []
        current_len = len(sections[0])

        for hit in hits:
            snippet = f"\n{hit.source_attribution} (Tier: {hit.tier.value}):\n{hit.content}\n"
            if current_len + len(snippet.encode("utf-8")) > max_bytes:
                break
            sections.append(snippet)
            citations.append(
                {
                    "id": hit.id,
                    "tier": hit.tier.value,
                    "attribution": hit.source_attribution,
                    "score": hit.score,
                }
            )
            current_len += len(snippet.encode("utf-8"))

        return {
            "context_text": "\n".join(sections),
            "citations": citations,
        }
