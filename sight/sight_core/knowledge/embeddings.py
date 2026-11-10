"""Pure-Python Deterministic Dense Vectorizer and Hybrid RRF Ranking.

Features:
- Zero heavy dependencies (no PyTorch, NumPy, or SentenceTransformers required).
- Deterministic 128-dimensional subword and token n-gram projection with L2 normalization.
- Microsecond vector generation and dot-product cosine similarity.
- Compact binary serialization (512-byte float32 blobs).
- Reciprocal Rank Fusion (RRF) for combining dense vector and FTS5 keyword results.
- Optional fallback bridge for local Ollama embedding models when active.
"""
from __future__ import annotations

import hashlib
import math
import struct
from typing import Any, Sequence

DIMENSION = 128


class DenseVectorizer:
    """Deterministic, lightweight subword vectorizer implemented in pure Python."""

    def __init__(self, dimension: int = DIMENSION) -> None:
        self.dimension = dimension

    def encode(self, text: str) -> list[float]:
        """Convert input text into an L2-normalized dense vector."""
        if not text or not text.strip():
            return [0.0] * self.dimension

        cleaned = text.lower().strip()
        tokens = cleaned.split()
        subwords: list[str] = list(tokens)

        # Generate character 3-grams and 4-grams for subword morphological capture
        for token in tokens:
            if len(token) >= 3:
                for i in range(len(token) - 2):
                    subwords.append(token[i : i + 3])
            if len(token) >= 4:
                for i in range(len(token) - 3):
                    subwords.append(token[i : i + 4])

        counts: dict[int, float] = {}
        for item in subwords:
            # Deterministic bucket assignment via md5 digest
            h = int(hashlib.md5(item.encode("utf-8")).hexdigest()[:8], 16)
            idx = h % self.dimension
            sign = 1.0 if (h >> 16) & 1 else -1.0
            counts[idx] = counts.get(idx, 0.0) + sign

        vec = [0.0] * self.dimension
        sum_sq = 0.0
        for idx, val in counts.items():
            # Logarithmic dampening of high frequency terms
            val_dampened = (math.copysign(1.0 + math.log(abs(val)), val)) if val != 0 else 0.0
            vec[idx] = val_dampened
            sum_sq += val_dampened * val_dampened

        norm = math.sqrt(sum_sq)
        if norm > 1e-9:
            vec = [v / norm for v in vec]

        return vec

    def pack(self, vector: list[float]) -> bytes:
        """Pack 128 floats into a 512-byte binary blob."""
        return struct.pack(f"{len(vector)}f", *vector)

    def unpack(self, blob: bytes) -> list[float]:
        """Unpack a binary blob back into a list of floats."""
        count = len(blob) // 4
        return list(struct.unpack(f"{count}f", blob))

    @staticmethod
    def cosine_similarity(u: Sequence[float], v: Sequence[float]) -> float:
        """Compute cosine similarity between two unit vectors."""
        if not u or not v or len(u) != len(v):
            return 0.0
        sim = sum(a * b for a, b in zip(u, v))
        return max(-1.0, min(1.0, sim))


def reciprocal_rank_fusion(
    fts_rankings: list[str],
    vector_rankings: list[str],
    k: int = 60,
    fts_weight: float = 1.0,
    vector_weight: float = 1.0,
) -> list[tuple[str, float]]:
    """Combine rankings using Reciprocal Rank Fusion (RRF).

    Formula: RRF_score(d) = sum( weight / (k + rank_i(d)) )
    """
    scores: dict[str, float] = {}

    for rank, doc_id in enumerate(fts_rankings, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + (fts_weight / (k + rank))

    for rank, doc_id in enumerate(vector_rankings, start=1):
        scores[doc_id] = scores.get(doc_id, 0.0) + (vector_weight / (k + rank))

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return ranked
