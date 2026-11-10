"""Isolated Project Memory Subsystem for BEL.

Guarantees strict isolation across named project spaces (e.g. BEL, ADA,
Badami, Octo6). Tracks goals, decisions, architecture, choices, progress,
issues, dependencies, roadmaps, and relevant files with importance ratings.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .embeddings import DenseVectorizer, reciprocal_rank_fusion
from .types import ProjectCategory, ProjectRecord


class ProjectMemoryService:
    """Manages structured, isolated memory partitions for distinct projects."""

    def __init__(self, store, vectorizer: DenseVectorizer | None = None, clock=time.time) -> None:
        self.store = store
        self.vectorizer = vectorizer or DenseVectorizer()
        self.clock = clock

    def add_record(
        self,
        project_id: str,
        category: ProjectCategory | str,
        title: str,
        content: str,
        importance: int = 3,
        confidence: float = 1.0,
        expiry: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectRecord:
        """Add a new structured record to an isolated project space."""
        if not project_id or not project_id.strip():
            raise ValueError("project_id is required and cannot be empty")

        cat = category if isinstance(category, ProjectCategory) else ProjectCategory(category)
        now = self.clock()
        rec_id = str(uuid.uuid4())
        meta = metadata or {}

        record = ProjectRecord(
            id=rec_id,
            project_id=project_id,
            category=cat,
            title=title.strip(),
            content=content.strip(),
            importance=max(1, min(5, importance)),
            confidence=max(0.0, min(1.0, confidence)),
            created_at=now,
            updated_at=now,
            expiry=expiry,
            metadata=meta,
        )

        # Generate dense vector for semantic search
        search_text = f"{record.title}\n{record.content}"
        vec = self.vectorizer.encode(search_text)
        packed_vec = self.vectorizer.pack(vec)

        with self.store.connect() as db:
            db.execute(
                """INSERT INTO project_memory(
                    id, project_id, category, title, content, importance,
                    confidence, created_at, updated_at, expiry, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.id,
                    record.project_id,
                    record.category.value,
                    record.title,
                    record.content,
                    record.importance,
                    record.confidence,
                    record.created_at,
                    record.updated_at,
                    record.expiry,
                    json.dumps(record.metadata),
                ),
            )
            db.execute(
                """INSERT OR REPLACE INTO memory_vectors(
                    id, store, project_id, dimension, vector, updated_at
                ) VALUES (?, 'project', ?, ?, ?, ?)""",
                (record.id, record.project_id, len(vec), packed_vec, now),
            )

        self.store.event(
            "project_memory.added",
            record.id,
            {"project_id": project_id, "category": cat.value, "title": title},
        )
        return record

    def get_record(self, project_id: str, record_id: str) -> ProjectRecord | None:
        """Retrieve a record ensuring strict project-id matching (fail-closed)."""
        now = self.clock()
        with self.store.connect() as db:
            row = db.execute(
                """SELECT * FROM project_memory 
                   WHERE id = ? AND project_id = ? 
                   AND (expiry IS NULL OR expiry > ?)""",
                (record_id, project_id, now),
            ).fetchone()

            if not row:
                return None

            return self._row_to_record(row)

    def update_record(
        self,
        project_id: str,
        record_id: str,
        title: str | None = None,
        content: str | None = None,
        importance: int | None = None,
        confidence: float | None = None,
        expiry: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProjectRecord:
        """Update an existing record within its strict project partition."""
        existing = self.get_record(project_id, record_id)
        if not existing:
            raise ValueError(f"Record {record_id} not found in project '{project_id}'")

        now = self.clock()
        new_title = title.strip() if title is not None else existing.title
        new_content = content.strip() if content is not None else existing.content
        new_importance = (
            max(1, min(5, importance)) if importance is not None else existing.importance
        )
        new_confidence = (
            max(0.0, min(1.0, confidence)) if confidence is not None else existing.confidence
        )
        new_expiry = expiry if expiry is not None else existing.expiry
        new_meta = {**existing.metadata, **(metadata or {})}

        search_text = f"{new_title}\n{new_content}"
        vec = self.vectorizer.encode(search_text)
        packed_vec = self.vectorizer.pack(vec)

        with self.store.connect() as db:
            db.execute(
                """UPDATE project_memory SET
                    title = ?, content = ?, importance = ?, confidence = ?,
                    updated_at = ?, expiry = ?, metadata = ?
                   WHERE id = ? AND project_id = ?""",
                (
                    new_title,
                    new_content,
                    new_importance,
                    new_confidence,
                    now,
                    new_expiry,
                    json.dumps(new_meta),
                    record_id,
                    project_id,
                ),
            )
            db.execute(
                """INSERT OR REPLACE INTO memory_vectors(
                    id, store, project_id, dimension, vector, updated_at
                ) VALUES (?, 'project', ?, ?, ?, ?)""",
                (record_id, project_id, len(vec), packed_vec, now),
            )

        self.store.event(
            "project_memory.updated",
            record_id,
            {"project_id": project_id, "title": new_title},
        )
        return self.get_record(project_id, record_id)  # type: ignore

    def delete_record(self, project_id: str, record_id: str) -> bool:
        """Strictly delete a project record and its vector representation."""
        with self.store.connect() as db:
            cur = db.execute(
                "DELETE FROM project_memory WHERE id = ? AND project_id = ?",
                (record_id, project_id),
            )
            deleted = cur.rowcount > 0
            if deleted:
                db.execute(
                    "DELETE FROM memory_vectors WHERE id = ? AND project_id = ?",
                    (record_id, project_id),
                )

        if deleted:
            self.store.event(
                "project_memory.deleted", record_id, {"project_id": project_id}
            )
        return deleted

    def list_by_category(
        self, project_id: str, category: ProjectCategory | str
    ) -> list[ProjectRecord]:
        """List all active records for a specific category within a project space."""
        cat = category if isinstance(category, ProjectCategory) else ProjectCategory(category)
        now = self.clock()
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT * FROM project_memory 
                   WHERE project_id = ? AND category = ?
                   AND (expiry IS NULL OR expiry > ?)
                   ORDER BY importance DESC, updated_at DESC""",
                (project_id, cat.value, now),
            ).fetchall()

            return [self._row_to_record(r) for r in rows]

    def get_all_project_records(self, project_id: str) -> list[ProjectRecord]:
        """Retrieve all active records for a project space."""
        now = self.clock()
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT * FROM project_memory 
                   WHERE project_id = ?
                   AND (expiry IS NULL OR expiry > ?)
                   ORDER BY category ASC, importance DESC, updated_at DESC""",
                (project_id, now),
            ).fetchall()

            return [self._row_to_record(r) for r in rows]

    def search(
        self,
        project_id: str,
        query: str,
        limit: int = 5,
        min_score: float = 0.05,
    ) -> list[tuple[ProjectRecord, float]]:
        """Hybrid search strictly isolated to the specified project_id."""
        if not query or not query.strip():
            return []

        now = self.clock()
        query_vec = self.vectorizer.encode(query)

        with self.store.connect() as db:
            # 1. Keyword search over title and content
            words = [w.lower() for w in query.split() if len(w) > 2][:8]
            fts_matches: list[str] = []
            if words:
                like_clauses = " OR ".join(["(lower(title) LIKE ? OR lower(content) LIKE ?)" for _ in words])
                params: list[Any] = [project_id, now]
                for w in words:
                    params.extend([f"%{w}%", f"%{w}%"])
                rows = db.execute(
                    f"""SELECT id FROM project_memory 
                       WHERE project_id = ? 
                       AND (expiry IS NULL OR expiry > ?)
                       AND ({like_clauses})
                       LIMIT 20""",
                    params,
                ).fetchall()
                fts_matches = [r["id"] for r in rows]

            # 2. Vector search over project vectors
            vec_rows = db.execute(
                """SELECT id, vector FROM memory_vectors 
                   WHERE store = 'project' AND project_id = ?""",
                (project_id,),
            ).fetchall()

            vector_scores: list[tuple[str, float]] = []
            for r in vec_rows:
                unpacked = self.vectorizer.unpack(r["vector"])
                sim = self.vectorizer.cosine_similarity(query_vec, unpacked)
                vector_scores.append((r["id"], sim))

            vector_scores.sort(key=lambda x: x[1], reverse=True)
            vector_matches = [x[0] for x in vector_scores[:20]]

            # 3. Reciprocal Rank Fusion
            rrf_ranked = reciprocal_rank_fusion(fts_matches, vector_matches, k=20)

            # 4. Fetch and assemble records
            results: list[tuple[ProjectRecord, float]] = []
            for rec_id, score in rrf_ranked[:limit]:
                if score < min_score:
                    continue
                row = db.execute(
                    """SELECT * FROM project_memory WHERE id = ? AND project_id = ? 
                       AND (expiry IS NULL OR expiry > ?)""",
                    (rec_id, project_id, now),
                ).fetchone()
                if row:
                    results.append((self._row_to_record(row), score))

            return results

    def export_project_context_summary(self, project_id: str) -> str:
        """Produce a structured context block of key project knowledge."""
        records = self.get_all_project_records(project_id)
        if not records:
            return f"Project [{project_id}]: No explicit project memories recorded."

        lines = [f"=== PROJECT CONTEXT: {project_id} ==="]
        by_cat: dict[str, list[ProjectRecord]] = {}
        for r in records:
            by_cat.setdefault(r.category.value, []).append(r)

        for cat_name, items in sorted(by_cat.items()):
            lines.append(f"\n[{cat_name.upper()}]")
            for item in sorted(items, key=lambda x: x.importance, reverse=True):
                lines.append(f"- {item.title} (Importance: {item.importance}/5): {item.content}")

        return "\n".join(lines)

    @staticmethod
    def _row_to_record(row) -> ProjectRecord:
        return ProjectRecord(
            id=row["id"],
            project_id=row["project_id"],
            category=ProjectCategory(row["category"]),
            title=row["title"],
            content=row["content"],
            importance=row["importance"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            expiry=row["expiry"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )
