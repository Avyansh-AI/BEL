"""Comprehensive Test Suite for BEL Stage 3: Knowledge, Project Memory & RAG Subsystem.

Covers:
1. Pure-Python deterministic dense vectorizer, cosine similarity, and RRF.
2. Isolated project memory spaces (BEL, ADA, Badami, Octo6) with strict isolation.
3. Memory management: utility scoring, deduplication, conflict resolution & temporal superseding.
4. Cryptographically verifiable physical deletion.
5. Multi-format document RAG (TXT, MD, DOCX OOXML, CSV, JSON, Code) and source attribution.
6. Hierarchical memory coordinator unified retrieval and context synthesis.
7. Cognitive orchestrator integration with memory citations.
"""
from __future__ import annotations

import io
import math
import tempfile
import time
import zipfile
import pytest
from pathlib import Path

from sight_core.brain_store import BrainStore
from sight_core.memory import MemoryService, MemoryInput
from sight_core.knowledge import (
    ChunkStrategy,
    DenseVectorizer,
    DocumentFormat,
    HierarchicalMemoryCoordinator,
    MemoryManagementEngine,
    MemoryTier,
    ProjectCategory,
    ProjectMemoryService,
    RAGEngine,
    reciprocal_rank_fusion,
)
from sight_core.cognitive.orchestrator import CognitiveOrchestrator


@pytest.fixture
def temp_brain():
    """Create a temporary BrainStore initialized with version 3 schema."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = BrainStore(tmp_dir)
        yield store


# =====================================================================
# 1. Vectorizer & Hybrid Ranking Tests
# =====================================================================

def test_dense_vectorizer_determinism_and_norm():
    vec = DenseVectorizer(dimension=128)
    text = "BEL cognitive executive logic architecture and persistent memory"

    v1 = vec.encode(text)
    v2 = vec.encode(text)

    # Determinism
    assert len(v1) == 128
    assert v1 == v2

    # L2 unit normalization
    norm = math.sqrt(sum(x * x for x in v1))
    assert pytest.approx(norm, 1e-4) == 1.0


def test_dense_vectorizer_similarity_and_packing():
    vec = DenseVectorizer(dimension=128)
    t1 = "Quantum computing and qubit decoherence"
    t2 = "Quantum computing and quantum state fidelity"
    t3 = "Making pasta carbonara with eggs and guanciale"

    v1 = vec.encode(t1)
    v2 = vec.encode(t2)
    v3 = vec.encode(t3)

    sim_related = vec.cosine_similarity(v1, v2)
    sim_unrelated = vec.cosine_similarity(v1, v3)

    assert sim_related > sim_unrelated
    assert sim_related > 0.4
    assert vec.cosine_similarity(v1, v1) == pytest.approx(1.0, 1e-4)

    # Binary packing
    blob = vec.pack(v1)
    assert len(blob) == 512  # 128 * 4 bytes
    unpacked = vec.unpack(blob)
    assert len(unpacked) == 128
    assert pytest.approx(unpacked[0], 1e-5) == v1[0]


def test_reciprocal_rank_fusion():
    fts_rankings = ["doc-a", "doc-b", "doc-c"]
    vec_rankings = ["doc-b", "doc-d", "doc-a"]

    ranked = reciprocal_rank_fusion(fts_rankings, vec_rankings, k=60)
    top_doc, top_score = ranked[0]

    # doc-b appeared at rank 2 in FTS and rank 1 in Vector -> should win
    assert top_doc == "doc-b"
    assert top_score > 0.0


# =====================================================================
# 2. Strict Project Memory Isolation Tests
# =====================================================================

def test_project_memory_strict_isolation(temp_brain):
    pm = ProjectMemoryService(temp_brain)

    # Add records to distinct projects
    bel_rec = pm.add_record(
        project_id="BEL",
        category=ProjectCategory.ARCHITECTURE,
        title="Micro-Kernel Architecture",
        content="BEL core uses SQLite Phase 2/3 and zero-dependency vector embeddings.",
        importance=5,
    )

    badami_rec = pm.add_record(
        project_id="Badami",
        category=ProjectCategory.DECISION,
        title="Edge Sensor Mesh",
        content="Badami project requires RS-485 serial communication with industrial PLC.",
        importance=4,
    )

    ada_rec = pm.add_record(
        project_id="ADA",
        category=ProjectCategory.GOAL,
        title="Autonomous Driving Agent",
        content="ADA targets low-latency camera stream perception.",
        importance=3,
    )

    # Strict isolation verification: Badami must NEVER see BEL or ADA
    badami_records = pm.get_all_project_records("Badami")
    assert len(badami_records) == 1
    assert badami_records[0].id == badami_rec.id
    assert badami_records[0].title == "Edge Sensor Mesh"

    # Querying Badami for BEL record fails-closed
    assert pm.get_record("Badami", bel_rec.id) is None
    assert pm.get_record("BEL", bel_rec.id) is not None

    # Search isolation: search for 'SQLite' in Badami returns nothing
    badami_search = pm.search("Badami", "SQLite")
    assert len(badami_search) == 0

    bel_search = pm.search("BEL", "SQLite")
    assert len(bel_search) >= 1
    assert bel_search[0][0].id == bel_rec.id

    # Category listing
    arch_records = pm.list_by_category("BEL", ProjectCategory.ARCHITECTURE)
    assert len(arch_records) == 1
    assert arch_records[0].title == "Micro-Kernel Architecture"

    # Export project context summary
    bel_summary = pm.export_project_context_summary("BEL")
    assert "=== PROJECT CONTEXT: BEL ===" in bel_summary
    assert "Micro-Kernel Architecture" in bel_summary
    assert "Badami" not in bel_summary


def test_project_memory_update_and_delete(temp_brain):
    pm = ProjectMemoryService(temp_brain)
    rec = pm.add_record(
        project_id="Octo6",
        category=ProjectCategory.ISSUE,
        title="Thread Pool Starvation",
        content="Worker thread pool exhaustion during burst I/O.",
        importance=4,
    )

    # Update
    updated = pm.update_record(
        project_id="Octo6",
        record_id=rec.id,
        content="Worker thread pool resolved by adding bounded work queue.",
        importance=2,
    )
    assert updated.content == "Worker thread pool resolved by adding bounded work queue."
    assert updated.importance == 2

    # Cross-project update fails
    with pytest.raises(ValueError, match="not found in project"):
        pm.update_record("BEL", rec.id, title="Hacked")

    # Delete
    assert pm.delete_record("Octo6", rec.id) is True
    assert pm.get_record("Octo6", rec.id) is None


# =====================================================================
# 3. Memory Management: Utility, Duplication, Conflict Resolution
# =====================================================================

def test_memory_management_utility_scoring(temp_brain):
    mgr = MemoryManagementEngine(temp_brain)
    now = 1_000_000
    mgr.clock = lambda: now

    # High importance, fresh memory
    u_fresh = mgr.evaluate_utility(importance=5, confidence=1.0, created_at=now)
    # Low importance, fresh memory
    u_low = mgr.evaluate_utility(importance=1, confidence=0.5, created_at=now)
    # High importance, 90 days old (3 half-lives)
    u_old = mgr.evaluate_utility(importance=5, confidence=1.0, created_at=now - (90 * 86400))

    assert u_fresh > u_low
    assert u_fresh > u_old
    assert 0.0 <= u_low <= 1.0


def test_memory_management_duplicate_detection(temp_brain):
    pm = ProjectMemoryService(temp_brain)
    mgr = MemoryManagementEngine(temp_brain)

    rec = pm.add_record(
        project_id="BEL",
        category=ProjectCategory.CHOICE,
        title="Frontend Framework",
        content="We chose React 19 and Tailwind CSS for the user interface.",
    )

    # Exact duplicate
    dup_id, sim = mgr.detect_duplicate("We chose React 19 and Tailwind CSS for the user interface.", "BEL")
    assert dup_id == rec.id
    assert sim == 1.0

    # Near duplicate with threshold
    near_id, near_sim = mgr.detect_duplicate("We selected React 19 and Tailwind CSS for the frontend UI.", "BEL", threshold=0.60)
    assert near_id == rec.id
    assert near_sim >= 0.60

    # High similarity paraphrase (with title)
    close_id, close_sim = mgr.detect_duplicate("We chose React 19 and Tailwind CSS for our user interface.", "BEL", title="Frontend Framework")
    assert close_id == rec.id
    assert close_sim >= 0.90

    # Cross project should NOT match
    other_id, _ = mgr.detect_duplicate("We chose React 19 and Tailwind CSS for the user interface.", "Badami")
    assert other_id is None


def test_conflict_resolution_and_temporal_superseding(temp_brain):
    mem = MemoryService(temp_brain)
    mgr = MemoryManagementEngine(temp_brain)

    # Store initial user preference
    mem.put(MemoryInput(key="theme", content="dark_mode", confidence=1.0, project_id="default"))

    # Case 1: Newer explicit user correction supersedes older fact
    res1 = mgr.resolve_conflict(
        new_key="theme",
        new_content="solarized_light",
        project_id="default",
        new_confidence=1.0,
        is_explicit_correction=True,
    )
    assert res1.status == "superseded"
    assert res1.superseded_content == "dark_mode"

    # Case 2: Inferred conflicting statement with lower confidence flags contradiction
    res2 = mgr.resolve_conflict(
        new_key="theme",
        new_content="high_contrast",
        project_id="default",
        new_confidence=0.5,
        is_explicit_correction=False,
    )
    assert res2.status == "contradiction_flagged"

    # Case 3: Identical statement is retained
    res3 = mgr.resolve_conflict(
        new_key="theme",
        new_content="dark_mode",
        project_id="default",
    )
    assert res3.status == "retained"


def test_verifiable_cryptographic_deletion(temp_brain):
    pm = ProjectMemoryService(temp_brain)
    mgr = MemoryManagementEngine(temp_brain)

    rec = pm.add_record(
        project_id="BEL",
        category=ProjectCategory.GOAL,
        title="Ephemeral Secret",
        content="This classified goal must be verifiably erased.",
    )

    # Confirm present in DB
    assert pm.get_record("BEL", rec.id) is not None

    # Execute verifiable deletion
    proof = mgr.verifiable_delete(rec.id, project_id="BEL")
    assert proof["record_id"] == rec.id
    assert proof["deleted_rows"] >= 1
    assert proof["verified_clean"] is True
    assert len(proof["proof_hash"]) == 64  # SHA-256

    # Confirm totally gone
    assert pm.get_record("BEL", rec.id) is None


# =====================================================================
# 4. Multi-Format Document RAG Tests (TXT, MD, DOCX, CSV, JSON, Code)
# =====================================================================

def test_rag_ingest_markdown_hierarchical(temp_brain):
    rag = RAGEngine(temp_brain)
    md_content = """# System Overview
BEL is an autonomous executive AI assistant.

## Architecture Guidelines
The core architecture follows a micro-kernel pattern.
Hardware sentry monitors system RAM and GPU VRAM continuously.

## Security Policies
All code edits create transactional backup journals.
"""
    doc = rag.ingest_text(
        title="Architecture Guide",
        text=md_content,
        project_id="BEL",
        doc_format=DocumentFormat.MARKDOWN,
        strategy=ChunkStrategy.HIERARCHICAL_MARKDOWN,
    )

    assert doc.total_chunks >= 2
    chunks = rag.search("hardware sentry RAM", project_id="BEL")
    assert len(chunks) >= 1
    assert "Section: Architecture Guidelines" in chunks[0].content
    assert chunks[0].source_attribution == f"[{doc.title}:chunk_1]"


def test_rag_ingest_pure_python_docx(temp_brain):
    rag = RAGEngine(temp_brain)

    # Construct in-memory valid OOXML .docx zip
    docx_bytes = io.BytesIO()
    with zipfile.ZipFile(docx_bytes, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        xml_content = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
    <w:body>
        <w:p><w:r><w:t>Project Specification for Antigravity BEL.</w:t></w:r></w:p>
        <w:p><w:r><w:t>The neural engine utilizes local DeepSeek-R1 inference.</w:t></w:r></w:p>
    </w:body>
</w:document>"""
        zf.writestr("word/document.xml", xml_content)

    extracted_text = rag._extract_docx(docx_bytes.getvalue())
    assert "Project Specification for Antigravity BEL." in extracted_text
    assert "neural engine utilizes local DeepSeek-R1" in extracted_text

    doc = rag.ingest_text(
        title="Spec Doc",
        text=extracted_text,
        project_id="BEL",
        doc_format=DocumentFormat.DOCX,
        strategy=ChunkStrategy.SEMANTIC_PARAGRAPH,
    )
    assert doc.total_chunks >= 1

    search_res = rag.search("DeepSeek-R1 neural engine", project_id="BEL")
    assert len(search_res) >= 1
    assert "DeepSeek-R1" in search_res[0].content


def test_rag_ingest_csv_and_json(temp_brain):
    rag = RAGEngine(temp_brain)

    # CSV
    csv_text = "id,name,role\n1,Tony Stark,Executive\n2,Jarvis,AI Assistant"
    doc_csv = rag.ingest_text(
        title="Personnel",
        text=rag._extract_csv(csv_text),
        project_id="BEL",
        doc_format=DocumentFormat.CSV,
    )
    assert doc_csv.total_chunks >= 1
    csv_hits = rag.search("Tony Stark", project_id="BEL")
    assert len(csv_hits) >= 1

    # JSON
    json_text = '{"service": "BEL_Gateway", "port": 8080, "protocol": "gRPC"}'
    doc_json = rag.ingest_text(
        title="Gateway Config",
        text=rag._extract_json(json_text),
        project_id="BEL",
        doc_format=DocumentFormat.JSON,
    )
    assert doc_json.total_chunks >= 1
    json_hits = rag.search("gateway protocol", project_id="BEL")
    assert len(json_hits) >= 1


def test_rag_code_aware_chunking(temp_brain):
    rag = RAGEngine(temp_brain)
    code = """import os
import sys

def initialize_sensor_hub():
    '''Connect to hardware sensor bus.'''
    bus = open_i2c_channel(0x42)
    return bus

class TelemetryCollector:
    def __init__(self, bus):
        self.bus = bus

    def read_metrics(self):
        return self.bus.read_all()
"""
    doc = rag.ingest_text(
        title="SensorHub Code",
        text=code,
        project_id="Badami",
        doc_format=DocumentFormat.CODE,
        strategy=ChunkStrategy.CODE_AWARE,
    )
    assert doc.total_chunks >= 1
    hits = rag.search("TelemetryCollector read_metrics", project_id="Badami")
    assert len(hits) >= 1
    assert "class TelemetryCollector" in hits[0].content


# =====================================================================
# 5. Hierarchical Memory Coordinator Tests
# =====================================================================

def test_hierarchical_coordinator_unified_retrieval(temp_brain):
    coord = HierarchicalMemoryCoordinator(temp_brain)

    # 1. Add Project Memory
    coord.remember(
        tier=MemoryTier.PROJECT,
        project_id="BEL",
        key="db_engine",
        title="Database Engine",
        content="BEL uses SQLite 3 with WAL mode and secure deletion.",
        importance=5,
    )

    # 2. Add Long-Term Profile
    coord.remember(
        tier=MemoryTier.LONG_TERM,
        project_id="BEL",
        key="coding_style",
        content="User prefers strict typing, zero bloat, and KaTeX math formatting.",
    )

    # 3. Add Document RAG
    coord.remember(
        tier=MemoryTier.DOCUMENT_RAG,
        project_id="BEL",
        key="deployment_guide",
        title="Deployment Manual",
        content="To deploy BEL on Windows 11, execute run.ps1 inside the active venv.",
    )

    # Multi-tier unified retrieval
    results = coord.retrieve("SQLite WAL mode", project_id="BEL")
    assert len(results) >= 1
    top = results[0]
    assert top.tier == MemoryTier.PROJECT
    assert "[BEL:decision:Database Engine]" in top.source_attribution

    # Synthesize context for LLM prompt
    synth = coord.synthesize_context("Tell me about the database and deployment", project_id="BEL")
    assert "=== RETRIEVED MEMORY & KNOWLEDGE ===" in synth["context_text"]
    assert len(synth["citations"]) >= 1


# =====================================================================
# 6. Cognitive Orchestrator Memory Integration Tests
# =====================================================================

@pytest.mark.anyio
async def test_cognitive_orchestrator_with_hierarchical_memory(temp_brain):
    coord = HierarchicalMemoryCoordinator(temp_brain)

    # Store project decision
    coord.remember(
        tier=MemoryTier.PROJECT,
        project_id="BEL",
        key="audio_sampling",
        title="Acoustic Processing",
        content="Orb visualizer renders 520 Fibonacci points at 60 FPS using Web Audio API.",
        importance=4,
    )

    orch = CognitiveOrchestrator(memory=coord)

    # Turn querying about the visualizer
    res = await orch.process_turn("Tell me about the acoustic orb visualizer", project_id="BEL")
    assert res["status"] == "ok"
    assert "citations" in res
    assert len(res["citations"]) >= 1
    assert "Acoustic Processing" in res["citations"][0]["attribution"]
    assert "Informed by knowledge" in res["say"]


# =====================================================================
# 7. Learning API Project Memory & RAG REST Endpoints Tests
# =====================================================================

def test_learning_api_project_and_rag_endpoints(client):
    def invoke(operation, args):
        path = "/api/learning/" + operation
        prepared = client.post("/api/actions/prepare", json={"path": path, "args": args})
        assert prepared.status_code == 200, prepared.text
        grant = prepared.json()
        return client.post(path, json=grant["args"] | {"actionApproval": grant["approvalId"]})

    # 1. Project Memory Add
    proj_res = invoke("projects/add", {
        "project_id": "Badami",
        "category": "goal",
        "title": "Autonomous Navigation",
        "content": "Implement sensor fusion SLAM algorithm.",
        "importance": 4,
    })
    assert proj_res.status_code == 200, proj_res.text
    rec = proj_res.json()
    assert rec["project_id"] == "Badami"
    assert rec["title"] == "Autonomous Navigation"

    # Read project records
    records_res = client.get("/api/learning/projects/Badami/records")
    assert records_res.status_code == 200
    assert len(records_res.json()["items"]) == 1

    # Project search
    search_res = client.get("/api/learning/projects/Badami/search", params={"q": "sensor fusion"})
    assert search_res.status_code == 200
    assert len(search_res.json()["items"]) >= 1

    # 2. RAG Ingest
    rag_res = invoke("rag/ingest", {
        "project_id": "Badami",
        "title": "SLAM Manual",
        "text": "Extended Kalman Filter integrates IMU and wheel odometry readings.",
        "doc_format": "markdown",
        "strategy": "semantic_paragraph",
    })
    assert rag_res.status_code == 200, rag_res.text
    doc = rag_res.json()
    assert doc["title"] == "SLAM Manual"

    # Read RAG documents
    docs_res = client.get("/api/learning/rag/documents", params={"project_id": "Badami"})
    assert docs_res.status_code == 200
    assert len(docs_res.json()["items"]) == 1

    # RAG search
    rag_search_res = client.get("/api/learning/rag/search", params={"project_id": "Badami", "q": "Kalman Filter"})
    assert rag_search_res.status_code == 200
    assert len(rag_search_res.json()["items"]) >= 1

    # 3. Unified Memory Retrieval
    unified_res = client.get("/api/learning/memory/unified", params={"project_id": "Badami", "q": "SLAM Kalman"})
    assert unified_res.status_code == 200
    assert len(unified_res.json()["items"]) >= 1

    # 4. Verifiable Deletion
    verif_res = invoke("memory/verifiable_delete", {"id": rec["id"], "project_id": "Badami"})
    assert verif_res.status_code == 200, verif_res.text
    assert verif_res.json()["verified_clean"] is True

    # 5. Delete RAG Document
    del_rag_res = invoke("rag/delete", {"id": doc["id"], "project_id": "Badami"})
    assert del_rag_res.status_code == 200, del_rag_res.text
    assert del_rag_res.json()["deleted"] is True
