# BEL (Behavioral Executive Logic) — Stage 2 Test Report
**Test Execution Date:** November 10, 2026  
**Test Suite:** `tests/test_cognitive.py` + Full Major Regression Suite  
**Test Harness:** `pytest 9.0.3` (Python 3.12.5), `node 22+`  
**Overall Result:** **201 / 201 Major Backend Tests Passed (100% Pass Rate)**  

---

## 1. Stage 2 Cognitive Suite Results (`tests/test_cognitive.py`)

| Test Name | Domain | Verification Scope | Status | Duration |
| :--- | :--- | :--- | :---: | :---: |
| `test_intent_classification_conversation` | NLU | Classifies general knowledge queries as `CONVERSATION` | **PASS** | 0.005s |
| `test_intent_classification_tool_action` | NLU | Extracts target file and classifies single tool actions | **PASS** | 0.004s |
| `test_intent_classification_multi_step_plan` | NLU | Splits multi-part instructions (`and then`) into task plans | **PASS** | 0.004s |
| `test_intent_classification_serious_mode` | NLU | Detects explicit Serious Mode deliberation requests | **PASS** | 0.004s |
| `test_intent_classification_ambiguity_detection` | NLU | Identifies missing parameters and emits clarification prompts | **PASS** | 0.004s |
| `test_context_retention_and_anaphora_resolution` | Context | Resolves "that file" to previously referenced `experiment.py` | **PASS** | 0.004s |
| `test_context_task_tracking` | Context | Tracks ongoing task lifecycle (`running` -> `completed`) | **PASS** | 0.004s |
| `test_reasoning_task_decomposition` | Reasoning | Breaks compound instructions into ordered sub-problems | **PASS** | 0.004s |
| `test_planning_dependency_execution_order` | Planning | Enforces step dependency readiness before execution | **PASS** | 0.005s |
| `test_dynamic_replanning_on_step_failure` | Planning | Cancels downstream dependent steps upon upstream failure | **PASS** | 0.004s |
| `test_permission_classification` | Decision | Categorizes `READ_ONLY`, `REVERSIBLE`, `CONSEQUENTIAL`, `DESTRUCTIVE` | **PASS** | 0.004s |
| `test_task_aware_model_routing` | Decision | Routes tasks appropriately (Gemma, DeepSeek-R1, Qwen Coder, Gemini) | **PASS** | 0.004s |
| `test_tokenharbor_provider_contract` | Routing | Validates Token Harbor policy schema and pricing structure | **PASS** | 0.004s |
| `test_serious_mode_deliberation_consensus` | Serious Mode | Gathers 3 independent model perspectives and synthesizes outcome | **PASS** | 0.006s |
| `test_serious_mode_contradiction_detection` | Serious Mode | Detects conflicting feasibility recommendations across models | **PASS** | 0.005s |
| `test_outcome_verification_truth_enforcement` | Verification | Rejects unverified tool claims; confirms SHA256 / Undo IDs | **PASS** | 0.004s |
| `test_orchestrator_multi_step_proposal` | Orchestration | End-to-end multi-step task plan proposal with pending confirmation | **PASS** | 0.006s |
| `test_orchestrator_ambiguity_clarification` | Orchestration | End-to-end prompt clarification for missing app target | **PASS** | 0.005s |
| **Cognitive Suite Subtotal** | **18 Items** | **18 Passed, 0 Failed** | **100% PASS** | **0.09s** |

---

## 2. Major Regression Test Execution

| Test File | Total Items | Passed | Failed | Duration | Status |
| :--- | :---: | :---: | :---: | :---: | :---: |
| `test_cognitive.py` | 18 | 18 | 0 | 0.09s | **PASS** |
| `test_bel_identity.py` | 11 | 11 | 0 | 0.05s | **PASS** |
| `test_bel_tools.py` | 27 | 27 | 0 | 5.06s | **PASS** |
| `test_bel_desktop.py` | 18 | 18 | 0 | 0.22s | **PASS** |
| `test_system_monitor.py` | 8 | 8 | 0 | 0.19s | **PASS** |
| `test_bel_pre_compress.py` | 2 | 2 | 0 | 0.95s | **PASS** |
| `test_windows_apps.py` | 20 | 20 | 0 | 0.06s | **PASS** |
| `test_needle.py` | 45 | 45 | 0 | 0.65s | **PASS** |
| `test_routing.py` | 27 | 27 | 0 | 1.14s | **PASS** |
| `test_learning.py` | 25 | 25 | 0 | 9.18s | **PASS** |
| **Backend Total** | **201** | **201** | **0** | **21.41s** | **100% PASS** |
| **Frontend Test Suite** | **26** | **26** | **0** | **0.22s** | **100% PASS** |
| **Total Automated Tests** | **227** | **227** | **0** | **~22s** | **100% PASS** |
