# BEL V1.0 — Performance Benchmark Report

**Release Version:** `1.0.0-RC1`  
**Hardware Environment:** Windows 11 (x64) · 16,068 MiB RAM · **NVIDIA GeForce RTX 4060 Laptop GPU** (`8,188 MiB VRAM`)  
**Python Runtime:** Python 3.12.5 (`sight/.venv`)

---

## 1. Subsystem Latency & Throughput Benchmarks

| Subsystem / Operation | Measured Latency / Metric | Target SLA | Status |
| :--- | :--- | :--- | :---: |
| **Cognitive Orchestrator Initialization** | `0.01 ms` | `< 50 ms` | **PASS** |
| **NLU Intent, Entity & Contradiction Parse (`InputUnderstanding.parse`)** | `0.013 ms` avg (`~76,900 ops/s`) | `< 5 ms` | **PASS** |
| **Fast-Path Needle Router Dispatch** | `< 1.0 ms` | `< 10 ms` | **PASS** |
| **Hybrid Memory Retrieval (`PersonalMemoryManager.retrieve`)** | `0.059 ms` avg (`~16,900 queries/s`) | `< 25 ms` | **PASS** |
| **SQLite WAL Memory Persistence Write (`PersonalMemoryManager.add`)** | `3.396 ms` avg | `< 20 ms` | **PASS** |
| **Multi-Agent 3-Role Parallel DAG + Deduplication + Manager Synthesis** | `3.01 ms` | `< 100 ms` | **PASS** |
| **Skill Forging AST Audit + Isolated `python -I` Subprocess Sandbox Suite** | `124.90 ms` | `< 1,000 ms` | **PASS** |
| **Autonomous Engine 3-Step Parallel DAG + SQLite Checkpoints + Evidence Verification** | `134.32 ms` | `< 500 ms` | **PASS** |
| **REST `/api/health` & `/api/bel/status` Local API Response** | `< 15 ms` | `< 100 ms` | **PASS** |

---

## 2. Host Resource & Hardware Telemetry

- **GPU / VRAM Discovery:** Detected **NVIDIA GeForce RTX 4060 Laptop GPU** (`8,188 MiB` total VRAM, `7,946 MiB` free VRAM, `2.9%` idle VRAM utilization; `safe_for_inference: true`).
- **Idle CPU Overhead:** `0.0% – 0.4%` when waiting on async event loops (`_wakeup.wait()`).
- **Soak Memory Stability:** Across **1,128 continuous soak cycles (`18,048` subsystem checks over `3.41 hours`)**, Python process RSS remained bounded with `0` memory leaks, `0` unclosed SQLite handles, and `0` crashes.

---

## 3. Performance Optimisations Applied

1. **Reasoning Depth Selection (`fast` / `standard` / `deep`):** Direct system queries and single-step tool actions use `fast` depth and the Fast-Path Needle router, eliminating redundant LLM calls.
2. **Multi-Agent Work Deduplication:** Identical `(role, capability, description)` subtasks within a project execution share verified output (`0` extra tokens consumed).
3. **Idempotent Step Guard in Autonomous Engine:** Completed steps with verified evidence are skipped immediately on task resume/recovery, avoiding duplicate I/O and tool invocations.
