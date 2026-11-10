"""Types and Data Models for BEL Knowledge, Memory & RAG Subsystem.

Defines schemas for hierarchical memory tiers, project spaces, document
ingestion, chunking strategies, hybrid retrieval, and conflict resolution.
"""
from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class MemoryTier(str, Enum):
    """Hierarchical memory tiers defined for BEL."""
    WORKING = "working"          # Active in-flight context, scratchpad, active goals
    SHORT_TERM = "short_term"    # Ephemeral turns, recent session state, rolling buffer
    LONG_TERM = "long_term"      # User preferences, verified personal facts, operational habits
    PROJECT = "project"          # Isolated project memory (BEL, ADA, Badami, Octo6, etc.)
    SEMANTIC = "semantic"        # Universal technology concepts, coding patterns, facts
    EPISODIC = "episodic"        # Chronological execution logs, receipts, historical decisions
    DOCUMENT_RAG = "document_rag" # Multi-format parsed documentation and knowledge corpus


class ProjectCategory(str, Enum):
    """Categories of structured knowledge stored inside isolated project spaces."""
    GOAL = "goal"
    DECISION = "decision"
    ARCHITECTURE = "architecture"
    CHOICE = "choice"
    PROGRESS = "progress"
    ISSUE = "issue"
    DEPENDENCY = "dependency"
    ROADMAP = "roadmap"
    FILE = "file"


class DocumentFormat(str, Enum):
    """Supported document formats for automated ingestion."""
    TXT = "txt"
    MARKDOWN = "markdown"
    PDF = "pdf"
    DOCX = "docx"
    CSV = "csv"
    JSON = "json"
    CODE = "code"
    UNKNOWN = "unknown"


class ChunkStrategy(str, Enum):
    """Strategies for breaking documents into retrieval chunks."""
    SLIDING_WINDOW = "sliding_window"
    SEMANTIC_PARAGRAPH = "semantic_paragraph"
    HIERARCHICAL_MARKDOWN = "hierarchical_markdown"
    CODE_AWARE = "code_aware"


class ProjectRecord(BaseModel):
    """A record stored in a dedicated, isolated project memory partition."""
    id: str
    project_id: str
    category: ProjectCategory
    title: str
    content: str
    importance: int = Field(default=3, ge=1, le=5)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: float
    updated_at: float
    expiry: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(BaseModel):
    """An indexed chunk of a parsed document with provenance."""
    id: str
    doc_id: str
    project_id: str
    chunk_index: int
    content: str
    token_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float
    score: float | None = None
    source_attribution: str | None = None


class RAGDocument(BaseModel):
    """A document registered in the RAG corpus."""
    id: str
    project_id: str
    title: str
    file_path: str | None = None
    mime_type: str
    content_hash: str
    total_chunks: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: float
    updated_at: float


class RetrievalResult(BaseModel):
    """Unified result from hybrid hierarchical memory search."""
    id: str
    tier: MemoryTier
    project_id: str
    title: str
    content: str
    score: float
    source_attribution: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConflictResolution(BaseModel):
    """Result of evaluating a memory entry against existing knowledge."""
    status: str  # 'superseded', 'updated', 'retained', 'contradiction_flagged'
    existing_id: str | None = None
    new_id: str | None = None
    reason: str
    superseded_content: str | None = None


class MemoryItem(BaseModel):
    """A generalized memory item representing working, short-term, or long-term facts."""
    id: str
    tier: MemoryTier
    key: str
    content: str
    confidence: float = 1.0
    importance: int = 3
    created_at: float
    updated_at: float
    expiry: float | None = None
    source_uri: str = "user_statement"
    metadata: dict[str, Any] = Field(default_factory=dict)
