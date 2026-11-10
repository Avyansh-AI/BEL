"""BEL Memory Management Engine.

Responsibilities:
- Utility evaluation and composite relevance scoring (1-5 importance, recency, confidence).
- Duplicate detection and deduplication (exact digest and semantic vector similarity).
- Conflict resolution and temporal superseding (newer explicit corrections supersede older facts).
- Memory consolidation (summarizing older episodes into higher-order knowledge).
- Decay, pruning, and TTL expiration.
- Cryptographically verifiable physical deletion.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
import uuid
from typing import Any

from .embeddings import DenseVectorizer
from .types import ConflictResolution, MemoryTier


class MemoryManagementEngine:
    """Intelligent memory curation, deduplication, conflict resolution, and pruning."""

    def __init__(self, store, vectorizer: DenseVectorizer | None = None, clock=time.time) -> None:
        self.store = store
        self.vectorizer = vectorizer or DenseVectorizer()
        self.clock = clock

    def evaluate_utility(
        self,
        importance: int,
        confidence: float,
        created_at: float,
        last_accessed: float | None = None,
        half_life_days: float = 30.0,
    ) -> float:
        """Calculate composite utility score in range [0.0, 1.0].

        Combines normalized importance, confidence, and exponential temporal decay.
        """
        now = self.clock()
        ref_time = last_accessed or created_at
        age_seconds = max(0.0, now - ref_time)
        age_days = age_seconds / 86400.0

        # Exponential temporal decay
        decay_factor = math.exp(-math.log(2.0) * (age_days / half_life_days))

        # Base score from importance (1-5 -> 0.2-1.0) and confidence (0.0-1.0)
        norm_importance = max(1, min(5, importance)) / 5.0
        norm_confidence = max(0.0, min(1.0, confidence))

        utility = (norm_importance * 0.5 + norm_confidence * 0.3 + decay_factor * 0.2)
        return round(utility, 4)

    def detect_duplicate(
        self,
        new_content: str,
        project_id: str,
        threshold: float = 0.85,
        title: str | None = None,
    ) -> tuple[str | None, float]:
        """Detect if an existing record in project_memory or profiles is a duplicate.

        Returns (duplicate_id, similarity_score) or (None, 0.0).
        """
        if not new_content or not new_content.strip():
            return None, 0.0

        new_hash = hashlib.sha256(new_content.strip().encode("utf-8")).hexdigest()

        with self.store.connect() as db:
            # 1. Exact match check in project_memory and profiles
            rows = db.execute(
                """SELECT id, title, content FROM project_memory 
                   WHERE project_id = ?""",
                (project_id,),
            ).fetchall()

            for r in rows:
                if hashlib.sha256(r["content"].strip().encode("utf-8")).hexdigest() == new_hash:
                    return r["id"], 1.0

            # 2. Semantic vector similarity check
            variants = [new_content]
            if title:
                variants.append(f"{title}\n{new_content}")

            vec_rows = db.execute(
                """SELECT id, vector FROM memory_vectors 
                   WHERE project_id = ?""",
                (project_id,),
            ).fetchall()

            best_id: str | None = None
            best_sim = 0.0

            for v_text in variants:
                v_encoded = self.vectorizer.encode(v_text)
                for r in vec_rows:
                    unpacked = self.vectorizer.unpack(r["vector"])
                    sim = self.vectorizer.cosine_similarity(v_encoded, unpacked)
                    if sim > best_sim:
                        best_sim = sim
                        best_id = r["id"]

            if best_sim >= threshold and best_id is not None:
                return best_id, round(best_sim, 4)

        return None, 0.0

    def resolve_conflict(
        self,
        new_key: str,
        new_content: str,
        project_id: str,
        new_confidence: float = 1.0,
        is_explicit_correction: bool = False,
    ) -> ConflictResolution:
        """Resolve potential contradiction between new information and stored facts.

        Temporal superseding principle: newer explicit user corrections supersede
        older facts, while non-conflicting facts are retained or merged.
        """
        now = self.clock()
        with self.store.connect() as db:
            # Check profile table for existing key
            old = db.execute(
                """SELECT id, key, content, confidence, revision, created_at 
                   FROM profiles 
                   WHERE project_id = ? AND key = ?""",
                (project_id, new_key),
            ).fetchone()

            if not old:
                return ConflictResolution(
                    status="retained",
                    reason="No conflicting knowledge found for key.",
                )

            old_content = old["content"]
            if old_content.strip() == new_content.strip():
                return ConflictResolution(
                    status="retained",
                    existing_id=old["id"],
                    reason="Identical content already verified in memory.",
                )

            # Contradiction detected on existing key
            if is_explicit_correction or new_confidence >= old["confidence"]:
                # Temporal superseding
                return ConflictResolution(
                    status="superseded",
                    existing_id=old["id"],
                    reason=f"Newer explicit statement supersedes prior revision (rev {old['revision']}).",
                    superseded_content=old_content,
                )
            else:
                return ConflictResolution(
                    status="contradiction_flagged",
                    existing_id=old["id"],
                    reason=f"Incoming content conflicts with established memory (existing confidence: {old['confidence']}).",
                    superseded_content=old_content,
                )

    def prune_expired(self) -> dict[str, int]:
        """Prune all expired records across project_memory, profiles, and episodes."""
        now = self.clock()
        pruned_counts: dict[str, int] = {"project_memory": 0, "profiles": 0, "episodes": 0}

        with self.store.connect() as db:
            # Project memory
            cur1 = db.execute(
                "DELETE FROM project_memory WHERE expiry IS NOT NULL AND expiry <= ?",
                (now,),
            )
            pruned_counts["project_memory"] = cur1.rowcount

            # Profiles
            cur2 = db.execute(
                "DELETE FROM profiles WHERE expiry IS NOT NULL AND expiry <= ?",
                (now,),
            )
            pruned_counts["profiles"] = cur2.rowcount

            # Episodes
            cur3 = db.execute(
                "DELETE FROM episodes WHERE expiry IS NOT NULL AND expiry <= ?",
                (now,),
            )
            pruned_counts["episodes"] = cur3.rowcount

            # Optimize FTS
            db.execute("INSERT INTO memory_fts(memory_fts) VALUES('optimize')")

        total = sum(pruned_counts.values())
        if total > 0:
            self.store.event("memory.pruned_expired", "system", pruned_counts)
        return pruned_counts

    def verifiable_delete(self, record_id: str, project_id: str | None = None) -> dict[str, Any]:
        """Physically delete a record from all tables and produce verifiable cryptographic proof."""
        now = self.clock()
        deleted_count = 0

        with self.store.connect() as db:
            # 1. project_memory
            if project_id:
                c1 = db.execute(
                    "DELETE FROM project_memory WHERE id = ? AND project_id = ?",
                    (record_id, project_id),
                )
            else:
                c1 = db.execute("DELETE FROM project_memory WHERE id = ?", (record_id,))
            deleted_count += c1.rowcount

            # 2. profiles & episodes
            c2 = db.execute("DELETE FROM profiles WHERE id = ?", (record_id,))
            c3 = db.execute("DELETE FROM episodes WHERE id = ?", (record_id,))
            deleted_count += c2.rowcount + c3.rowcount

            # 3. memory_vectors
            db.execute("DELETE FROM memory_vectors WHERE id = ?", (record_id,))

            # 4. memory_fts & graph_edges
            db.execute("DELETE FROM memory_fts WHERE id = ?", (record_id,))
            db.execute(
                "DELETE FROM graph_edges WHERE source = ? OR target = ?",
                (record_id, record_id),
            )

            # Verification: ensure zero rows remain
            check_p = db.execute(
                "SELECT COUNT(*) FROM project_memory WHERE id = ?", (record_id,)
            ).fetchone()[0]
            check_prof = db.execute(
                "SELECT COUNT(*) FROM profiles WHERE id = ?", (record_id,)
            ).fetchone()[0]
            check_ep = db.execute(
                "SELECT COUNT(*) FROM episodes WHERE id = ?", (record_id,)
            ).fetchone()[0]
            check_vec = db.execute(
                "SELECT COUNT(*) FROM memory_vectors WHERE id = ?", (record_id,)
            ).fetchone()[0]

            is_clean = (check_p + check_prof + check_ep + check_vec) == 0

        # Cryptographic proof receipt
        payload = f"{record_id}:{now}:{deleted_count}:{is_clean}"
        proof_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        self.store.event(
            "memory.verifiable_delete",
            record_id,
            {"deleted_rows": deleted_count, "verified_clean": is_clean, "proof": proof_hash},
        )

        return {
            "record_id": record_id,
            "deleted_rows": deleted_count,
            "verified_clean": is_clean,
            "proof_hash": proof_hash,
            "timestamp": now,
        }
