"""Advanced Multi-Format Document RAG Engine for BEL.

Supports:
- Multi-format ingestion: TXT, Markdown, DOCX (pure-Python OOXML), CSV, JSON, Code.
- Chunking strategies: Sliding-window, Semantic paragraph, Hierarchical markdown, Code-aware.
- Hybrid indexing: SQLite FTS5 + Dense vector embeddings.
- Reciprocal Rank Fusion (RRF) with relevance filtering.
- Precise source attribution: [doc_title:chunk_idx].
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .embeddings import DenseVectorizer, reciprocal_rank_fusion
from .types import ChunkStrategy, DocumentChunk, DocumentFormat, RAGDocument


class RAGEngine:
    """Document parsing, chunking, indexing, and hybrid retrieval engine."""

    def __init__(self, store, vectorizer: DenseVectorizer | None = None, clock=time.time) -> None:
        self.store = store
        self.vectorizer = vectorizer or DenseVectorizer()
        self.clock = clock

    # -------------------------------------------------------------------------
    # Document Ingestion & Parsing
    # -------------------------------------------------------------------------

    def ingest_text(
        self,
        title: str,
        text: str,
        project_id: str = "default",
        doc_format: DocumentFormat | str = DocumentFormat.TXT,
        strategy: ChunkStrategy | str = ChunkStrategy.SEMANTIC_PARAGRAPH,
        file_path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RAGDocument:
        """Ingest raw text into the document RAG corpus."""
        if not text or not text.strip():
            raise ValueError("Document text cannot be empty")

        fmt = doc_format if isinstance(doc_format, DocumentFormat) else DocumentFormat(doc_format)
        strat = strategy if isinstance(strategy, ChunkStrategy) else ChunkStrategy(strategy)
        now = self.clock()
        doc_id = str(uuid.uuid4())
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        # Generate chunks according to selected strategy
        raw_chunks = self._chunk_content(text, strat)
        total_chunks = len(raw_chunks)

        rag_doc = RAGDocument(
            id=doc_id,
            project_id=project_id,
            title=title.strip(),
            file_path=file_path,
            mime_type=f"text/{fmt.value}",
            content_hash=content_hash,
            total_chunks=total_chunks,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )

        with self.store.connect() as db:
            # 1. Register document
            db.execute(
                """INSERT INTO rag_documents(
                    id, project_id, title, file_path, mime_type, content_hash,
                    total_chunks, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    rag_doc.id,
                    rag_doc.project_id,
                    rag_doc.title,
                    rag_doc.file_path,
                    rag_doc.mime_type,
                    rag_doc.content_hash,
                    rag_doc.total_chunks,
                    json.dumps(rag_doc.metadata),
                    rag_doc.created_at,
                    rag_doc.updated_at,
                ),
            )

            # 2. Insert chunks, FTS index, and dense vectors
            for idx, chunk_text in enumerate(raw_chunks):
                chunk_id = f"{doc_id}-c{idx}"
                token_count = len(chunk_text.split())
                chunk_meta = {"chunk_index": idx, "doc_title": title}

                db.execute(
                    """INSERT INTO rag_chunks(
                        id, doc_id, project_id, chunk_index, content, token_count, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        chunk_id,
                        doc_id,
                        project_id,
                        idx,
                        chunk_text,
                        token_count,
                        json.dumps(chunk_meta),
                        now,
                    ),
                )

                db.execute(
                    "INSERT INTO rag_fts(id, doc_id, project_id, content) VALUES (?, ?, ?, ?)",
                    (chunk_id, doc_id, project_id, chunk_text),
                )

                # Generate dense vector for chunk
                vec = self.vectorizer.encode(chunk_text)
                packed_vec = self.vectorizer.pack(vec)
                db.execute(
                    """INSERT OR REPLACE INTO memory_vectors(
                        id, store, project_id, dimension, vector, updated_at
                    ) VALUES (?, 'rag', ?, ?, ?, ?)""",
                    (chunk_id, project_id, len(vec), packed_vec, now),
                )

        self.store.event(
            "rag.document_ingested",
            doc_id,
            {"title": title, "project_id": project_id, "chunks": total_chunks},
        )
        return rag_doc

    def ingest_file(
        self,
        file_path: str | Path,
        project_id: str = "default",
        strategy: ChunkStrategy | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RAGDocument:
        """Parse and ingest a file from disk into the RAG corpus."""
        p = Path(file_path)
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {p}")

        suffix = p.suffix.lower()
        title = p.stem

        if suffix in (".md", ".markdown"):
            text = p.read_text(encoding="utf-8", errors="replace")
            doc_fmt = DocumentFormat.MARKDOWN
            strat = strategy or ChunkStrategy.HIERARCHICAL_MARKDOWN
        elif suffix in (".docx",):
            text = self._extract_docx(p.read_bytes())
            doc_fmt = DocumentFormat.DOCX
            strat = strategy or ChunkStrategy.SEMANTIC_PARAGRAPH
        elif suffix in (".csv",):
            text = self._extract_csv(p.read_text(encoding="utf-8", errors="replace"))
            doc_fmt = DocumentFormat.CSV
            strat = strategy or ChunkStrategy.SEMANTIC_PARAGRAPH
        elif suffix in (".json",):
            text = self._extract_json(p.read_text(encoding="utf-8", errors="replace"))
            doc_fmt = DocumentFormat.JSON
            strat = strategy or ChunkStrategy.SEMANTIC_PARAGRAPH
        elif suffix in (".py", ".ts", ".tsx", ".js", ".sql", ".sh", ".ps1", ".html", ".css"):
            text = p.read_text(encoding="utf-8", errors="replace")
            doc_fmt = DocumentFormat.CODE
            strat = strategy or ChunkStrategy.CODE_AWARE
        else:
            text = p.read_text(encoding="utf-8", errors="replace")
            doc_fmt = DocumentFormat.TXT
            strat = strategy or ChunkStrategy.SLIDING_WINDOW

        return self.ingest_text(
            title=title,
            text=text,
            project_id=project_id,
            doc_format=doc_fmt,
            strategy=strat,
            file_path=str(p.resolve()),
            metadata=metadata,
        )

    # -------------------------------------------------------------------------
    # Format Extractors (Zero external dependencies)
    # -------------------------------------------------------------------------

    @staticmethod
    def _extract_docx(data: bytes) -> str:
        """Extract text from Microsoft Word (.docx) OOXML archive using standard library."""
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                xml_content = zf.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            paragraphs: list[str] = []
            for p_elem in tree.iter():
                if p_elem.tag.endswith("p"):
                    texts = [
                        t_elem.text
                        for t_elem in p_elem.iter()
                        if t_elem.tag.endswith("t") and t_elem.text
                    ]
                    if texts:
                        paragraphs.append("".join(texts))
            return "\n\n".join(paragraphs)
        except Exception as exc:
            raise ValueError(f"Failed to extract DOCX text: {exc}")

    @staticmethod
    def _extract_csv(content: str) -> str:
        """Convert tabular CSV into contextual row strings."""
        reader = csv.reader(io.StringIO(content))
        lines: list[str] = []
        headers: list[str] = []
        for i, row in enumerate(reader):
            if not row:
                continue
            if i == 0:
                headers = row
                lines.append(f"Headers: {', '.join(headers)}")
            else:
                row_items = [f"{h}: {v}" for h, v in zip(headers, row)]
                lines.append(f"Row {i}: " + "; ".join(row_items))
        return "\n".join(lines)

    @staticmethod
    def _extract_json(content: str) -> str:
        """Format JSON content into readable hierarchical structure."""
        data = json.loads(content)
        return json.dumps(data, indent=2)

    # -------------------------------------------------------------------------
    # Chunking Strategies
    # -------------------------------------------------------------------------

    def _chunk_content(self, text: str, strategy: ChunkStrategy) -> list[str]:
        if strategy == ChunkStrategy.HIERARCHICAL_MARKDOWN:
            return self._chunk_hierarchical_markdown(text)
        elif strategy == ChunkStrategy.CODE_AWARE:
            return self._chunk_code_aware(text)
        elif strategy == ChunkStrategy.SEMANTIC_PARAGRAPH:
            return self._chunk_semantic_paragraphs(text)
        else:
            return self._chunk_sliding_window(text)

    @staticmethod
    def _chunk_sliding_window(
        text: str, chunk_chars: int = 1200, overlap_chars: int = 200
    ) -> list[str]:
        """Sliding character/token window with overlap."""
        if len(text) <= chunk_chars:
            return [text.strip()]

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_chars
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start += chunk_chars - overlap_chars
        return chunks

    @staticmethod
    def _chunk_semantic_paragraphs(text: str, max_chars: int = 1400) -> list[str]:
        """Group paragraphs together without splitting mid-sentence."""
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if not paragraphs:
            return [text.strip()] if text.strip() else []

        chunks: list[str] = []
        current: list[str] = []
        current_len = 0

        for p in paragraphs:
            if current_len + len(p) > max_chars and current:
                chunks.append("\n\n".join(current))
                current = [p]
                current_len = len(p)
            else:
                current.append(p)
                current_len += len(p)

        if current:
            chunks.append("\n\n".join(current))
        return chunks

    @staticmethod
    def _chunk_hierarchical_markdown(text: str, max_chars: int = 1500) -> list[str]:
        """Hierarchical markdown chunking tracking section breadcrumbs."""
        lines = text.split("\n")
        chunks: list[str] = []
        current_breadcrumb = "Top"
        current_section: list[str] = []

        for line in lines:
            m = re.match(r"^(#{1,4})\s+(.+)$", line.strip())
            if m:
                if current_section:
                    body = "\n".join(current_section).strip()
                    if body:
                        chunks.append(f"[{current_breadcrumb}]\n{body}")
                    current_section = []
                current_breadcrumb = f"Section: {m.group(2).strip()}"
            current_section.append(line)

        if current_section:
            body = "\n".join(current_section).strip()
            if body:
                chunks.append(f"[{current_breadcrumb}]\n{body}")

        return chunks if chunks else [text.strip()]

    @staticmethod
    def _chunk_code_aware(text: str, max_lines: int = 50) -> list[str]:
        """Chunk source code along definition/class boundaries."""
        lines = text.split("\n")
        chunks: list[str] = []
        current_block: list[str] = []

        for line in lines:
            # Check for top-level definition boundaries
            is_def = re.match(r"^(async\s+def|def|class|function|export\s+class|interface)\s+", line)
            if is_def and len(current_block) >= 15:
                chunks.append("\n".join(current_block).strip())
                current_block = [line]
            elif len(current_block) >= max_lines:
                chunks.append("\n".join(current_block).strip())
                current_block = [line]
            else:
                current_block.append(line)

        if current_block:
            chunks.append("\n".join(current_block).strip())
        return chunks if chunks else [text.strip()]

    # -------------------------------------------------------------------------
    # Hybrid Retrieval & Source Attribution
    # -------------------------------------------------------------------------

    def search(
        self,
        query: str,
        project_id: str = "default",
        limit: int = 5,
        min_score: float = 0.05,
    ) -> list[DocumentChunk]:
        """Hybrid search combining SQLite FTS5 and dense vector embeddings with RRF."""
        if not query or not query.strip():
            return []

        query_vec = self.vectorizer.encode(query)

        with self.store.connect() as db:
            # 1. FTS5 Search
            words = re.findall(r"\w+", query, flags=re.UNICODE)[:10]
            fts_matches: list[str] = []
            if words:
                fts_query = " OR ".join(f'"{w.replace('"', '""')}"' for w in words)
                try:
                    rows = db.execute(
                        """SELECT id FROM rag_fts 
                           WHERE rag_fts MATCH ? AND project_id = ? 
                           ORDER BY rank LIMIT 25""",
                        (fts_query, project_id),
                    ).fetchall()
                    fts_matches = [r["id"] for r in rows]
                except Exception:
                    fts_matches = []

            # 2. Dense Vector Search
            vec_rows = db.execute(
                """SELECT id, vector FROM memory_vectors 
                   WHERE store = 'rag' AND project_id = ?""",
                (project_id,),
            ).fetchall()

            vector_scores: list[tuple[str, float]] = []
            for r in vec_rows:
                unpacked = self.vectorizer.unpack(r["vector"])
                sim = self.vectorizer.cosine_similarity(query_vec, unpacked)
                vector_scores.append((r["id"], sim))

            vector_scores.sort(key=lambda x: x[1], reverse=True)
            vector_matches = [x[0] for x in vector_scores[:25]]

            # 3. Reciprocal Rank Fusion
            rrf_ranked = reciprocal_rank_fusion(fts_matches, vector_matches, k=25)

            # 4. Fetch chunk records and attach source attributions
            chunks: list[DocumentChunk] = []
            for chunk_id, score in rrf_ranked[:limit]:
                if score < min_score:
                    continue
                row = db.execute(
                    """SELECT c.*, d.title as doc_title, d.file_path 
                       FROM rag_chunks c
                       JOIN rag_documents d ON c.doc_id = d.id
                       WHERE c.id = ? AND c.project_id = ?""",
                    (chunk_id, project_id),
                ).fetchone()

                if row:
                    attr = f"[{row['doc_title']}:chunk_{row['chunk_index']}]"
                    chunk_obj = DocumentChunk(
                        id=row["id"],
                        doc_id=row["doc_id"],
                        project_id=row["project_id"],
                        chunk_index=row["chunk_index"],
                        content=row["content"],
                        token_count=row["token_count"],
                        metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                        created_at=row["created_at"],
                        score=round(score, 4),
                        source_attribution=attr,
                    )
                    chunks.append(chunk_obj)

            return chunks

    def delete_document(self, doc_id: str, project_id: str = "default") -> bool:
        """Cascading deletion of document, chunks, FTS index, and vectors."""
        with self.store.connect() as db:
            # Get chunk IDs
            chunk_ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM rag_chunks WHERE doc_id = ? AND project_id = ?",
                    (doc_id, project_id),
                ).fetchall()
            ]

            # Delete document
            cur = db.execute(
                "DELETE FROM rag_documents WHERE id = ? AND project_id = ?",
                (doc_id, project_id),
            )
            deleted = cur.rowcount > 0

            if deleted:
                # Delete chunks
                db.execute("DELETE FROM rag_chunks WHERE doc_id = ?", (doc_id,))
                for cid in chunk_ids:
                    db.execute("DELETE FROM rag_fts WHERE id = ?", (cid,))
                    db.execute("DELETE FROM memory_vectors WHERE id = ?", (cid,))

        if deleted:
            self.store.event(
                "rag.document_deleted", doc_id, {"project_id": project_id}
            )
        return deleted

    def list_documents(self, project_id: str = "default") -> list[RAGDocument]:
        """List registered documents for a project."""
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT * FROM rag_documents 
                   WHERE project_id = ? 
                   ORDER BY updated_at DESC""",
                (project_id,),
            ).fetchall()

            docs: list[RAGDocument] = []
            for r in rows:
                docs.append(
                    RAGDocument(
                        id=r["id"],
                        project_id=r["project_id"],
                        title=r["title"],
                        file_path=r["file_path"],
                        mime_type=r["mime_type"],
                        content_hash=r["content_hash"],
                        total_chunks=r["total_chunks"],
                        metadata=json.loads(r["metadata"]) if r["metadata"] else {},
                        created_at=r["created_at"],
                        updated_at=r["updated_at"],
                    )
                )
            return docs
