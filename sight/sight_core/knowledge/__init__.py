"""BEL Knowledge, Memory and RAG Package.

Provides unified hierarchical memory, isolated project spaces, multi-format
document RAG, deterministic dense embeddings, and intelligent memory management.
"""
from __future__ import annotations

from .embeddings import DenseVectorizer, reciprocal_rank_fusion
from .hierarchical import HierarchicalMemoryCoordinator
from .manager import MemoryManagementEngine
from .project_memory import ProjectMemoryService
from .rag import RAGEngine
from .types import (
    ChunkStrategy,
    ConflictResolution,
    DocumentChunk,
    DocumentFormat,
    MemoryItem,
    MemoryTier,
    ProjectCategory,
    ProjectRecord,
    RAGDocument,
    RetrievalResult,
)

__all__ = [
    "ChunkStrategy",
    "ConflictResolution",
    "DenseVectorizer",
    "DocumentChunk",
    "DocumentFormat",
    "HierarchicalMemoryCoordinator",
    "MemoryItem",
    "MemoryManagementEngine",
    "MemoryTier",
    "ProjectCategory",
    "ProjectMemoryService",
    "ProjectRecord",
    "RAGDocument",
    "RAGEngine",
    "RetrievalResult",
    "reciprocal_rank_fusion",
]
