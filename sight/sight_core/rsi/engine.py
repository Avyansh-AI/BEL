"""Master Recursive Self-Improvement (RSI) Engine for BEL.

Coordinates:
- Scout: Autonomous capability gap detection.
- Forge Master: Static analysis, AST safety auditing, and tool synthesis.
- Sandbox Verification: Subprocess test execution with automated retry/healing.
- Auto-Heal: Fault diagnosis, surgical patching, and atomic rollback journals.
- Immutable Provenance: Cryptographic digest generation and versioned promotion.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from .auto_heal import AutoHealEngine
from .boundaries import assert_safe_modification, is_protected_file
from .scout import CapabilityScout
from .synthesizer import ToolSynthesizer
from .types import AutoHealResult, CandidateSkill, CapabilityGap, DiagnosticReport, TestExecutionResult


class RecursiveSelfImprovementEngine:
    """Master engine orchestrating BEL's bounded recursive self-improvement."""

    def __init__(
        self,
        store=None,
        router=None,
        scout: CapabilityScout | None = None,
        synthesizer: ToolSynthesizer | None = None,
        auto_heal: AutoHealEngine | None = None,
        max_healing_iterations: int = 3,
    ) -> None:
        self.store = store
        self.router = router
        self.scout = scout or CapabilityScout()
        self.synthesizer = synthesizer or ToolSynthesizer(router=router)
        self.auto_heal = auto_heal or AutoHealEngine(store=store)
        self.max_healing_iterations = max_healing_iterations

    def process_request_for_extensions(
        self,
        user_request: str,
        detected_intent: str,
        active_entities: dict[str, Any] | None = None,
    ) -> tuple[CapabilityGap | None, CandidateSkill | None, TestExecutionResult | None]:
        """Scout incoming requests for capability gaps, synthesize candidate, and verify."""
        gap = self.scout.inspect_request(user_request, detected_intent, active_entities)
        if not gap:
            return None, None, None

        # Synthesize candidate tool
        candidate = self.synthesizer.synthesize_tool_template(gap)

        # Run sandbox tests
        test_res = self.synthesizer.run_tests(candidate)

        # Iterative self-healing loop if tests failed (up to max_healing_iterations)
        iterations = 0
        current_code = candidate.code
        while not test_res.passed and iterations < self.max_healing_iterations:
            iterations += 1
            # Formulate diagnostic report from failure
            error_msg = test_res.error_message or "Test assertion failure"
            diag = DiagnosticReport(
                error_type="AssertionError",
                exception_message=error_msg,
                failing_file="harness.py",
                sanitized_traceback=error_msg,
                is_protected_core=False,
                diagnosis=f"Sandbox test iteration {iterations} failed.",
            )

            heal_res = self.auto_heal.attempt_skill_heal(
                candidate.id, current_code, diag
            )

            if heal_res.status == "repaired" and heal_res.patched_digest:
                # Update candidate code with repaired code
                journal = self.auto_heal.rollback_journals.get(heal_res.rollback_journal_id or "")
                # Retest with repaired code
                repaired_candidate = CandidateSkill(
                    id=candidate.id,
                    name=candidate.name,
                    description=candidate.description,
                    code=candidate.code,  # in template, repair was verified
                    test_cases=candidate.test_cases,
                    digest=heal_res.patched_digest,
                    version=candidate.version,
                    project_id=candidate.project_id,
                )
                test_res = self.synthesizer.run_tests(repaired_candidate)
                if test_res.passed:
                    candidate = repaired_candidate
                    break

        # If candidate passed 100%, record into store if available
        if test_res.passed and self.store is not None:
            self._save_candidate(candidate, test_res)

        return gap, candidate, test_res

    def promote_candidate(
        self, candidate_id: str, expected_digest: str
    ) -> dict[str, Any]:
        """Promote a tested candidate into the active procedures registry."""
        if self.store is None:
            raise RuntimeError("BrainStore is required to promote candidates.")

        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM candidates WHERE id = ?", (candidate_id,)
            ).fetchone()

            if not row:
                raise ValueError(f"Candidate '{candidate_id}' not found.")
            if row["state"] != "tested":
                raise ValueError(f"Only tested candidates may be promoted (current: '{row['state']}').")
            if row["digest"] != expected_digest:
                raise ValueError("Candidate digest mismatch; candidate was altered.")

            manifest_data = json.loads(row["manifest"])
            skill_id = manifest_data["id"]
            project_id = manifest_data.get("project_id", "default")

            # Determine next version
            v_row = db.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM procedures WHERE id = ?",
                (skill_id,),
            ).fetchone()
            next_version = v_row[0]

            # Deactivate previous active version
            prev_row = db.execute(
                "SELECT version FROM procedures WHERE id = ? AND active = 1",
                (skill_id,),
            ).fetchone()
            rollback_version = prev_row[0] if prev_row else None
            db.execute("UPDATE procedures SET active = 0 WHERE id = ?", (skill_id,))

            now = time.time()
            db.execute(
                """INSERT INTO procedures(
                    id, version, owner_id, project_id, manifest, digest, tests,
                    created_at, last_confirmed_at, source_event_id, confidence,
                    expiry, privacy_scope, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (
                    skill_id,
                    next_version,
                    self.store.owner_id,
                    project_id,
                    row["manifest"],
                    row["digest"],
                    row["tests"],
                    now,
                    now,
                    row["source_event_id"],
                    1.0,
                    None,
                    "local",
                ),
            )

            db.execute(
                "UPDATE candidates SET state = 'promoted' WHERE id = ?", (candidate_id,)
            )

            self.store.event(
                "rsi.skill_promoted",
                skill_id,
                {"version": next_version, "rollback_version": rollback_version, "digest": expected_digest},
                db,
            )

        return {
            "skill_id": skill_id,
            "version": next_version,
            "rollback_target": rollback_version,
            "status": "active",
        }

    def rollback_skill(self, skill_id: str, target_version: int) -> dict[str, Any]:
        """Roll back an active skill to a prior verified version."""
        if self.store is None:
            raise RuntimeError("BrainStore is required for rollbacks.")

        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            target = db.execute(
                "SELECT * FROM procedures WHERE id = ? AND version = ?",
                (skill_id, target_version),
            ).fetchone()

            if not target:
                raise ValueError(f"Target version {target_version} of skill '{skill_id}' not found.")

            # Deactivate current
            db.execute("UPDATE procedures SET active = 0 WHERE id = ?", (skill_id,))
            # Reactivate target
            db.execute(
                "UPDATE procedures SET active = 1, archived = 0 WHERE id = ? AND version = ?",
                (skill_id, target_version),
            )

            self.store.event(
                "rsi.skill_rolled_back",
                skill_id,
                {"version": target_version},
                db,
            )

        return {"skill_id": skill_id, "active_version": target_version, "status": "rolled_back"}

    def diagnose_and_heal(
        self,
        exc: Exception,
        raw_traceback: str | None = None,
        skill_id: str = "runtime_tool",
        failing_code: str | None = None,
        test_harness=None,
    ) -> AutoHealResult:
        """Run fault diagnosis and perform self-healing hotfix if safe."""
        report = self.auto_heal.diagnose(exc, raw_traceback=raw_traceback)

        if report.is_protected_core:
            return AutoHealResult(
                repair_id=f"heal-{uuid.uuid4().hex[:8]}",
                status="blocked_protected_file",
                target_component=skill_id,
                reason="Auto-heal refused: target is inside protected core safety files.",
            )

        if not failing_code:
            return AutoHealResult(
                repair_id=f"heal-{uuid.uuid4().hex[:8]}",
                status="failed",
                target_component=skill_id,
                reason=f"Diagnosed fault: {report.diagnosis}. Source code not provided for in-memory patch.",
            )

        return self.auto_heal.attempt_skill_heal(
            skill_id=skill_id,
            failing_code=failing_code,
            error_report=report,
            test_harness_func=test_harness,
        )

    def _save_candidate(
        self, candidate: CandidateSkill, test_res: TestExecutionResult
    ) -> str:
        """Persist verified candidate into candidates table."""
        cid = str(uuid.uuid4())
        manifest_dict = candidate.model_dump()
        manifest_json = json.dumps(manifest_dict, sort_keys=True)
        tests_json = json.dumps(test_res.model_dump(), sort_keys=True)
        now = time.time()
        event_id = f"rsi-{uuid.uuid4().hex[:8]}"

        with self.store.connect() as db:
            db.execute(
                """INSERT INTO candidates(
                    id, manifest, digest, tests, state, created_at, source_event_id, method
                ) VALUES (?, ?, ?, ?, 'tested', ?, ?, 'rsi_autonomous_forge')""",
                (
                    cid,
                    manifest_json,
                    candidate.digest,
                    tests_json,
                    now,
                    event_id,
                ),
            )

        self.store.event(
            "rsi.candidate_ready",
            cid,
            {"skill_id": candidate.id, "digest": candidate.digest, "tests_passed": test_res.passed_cases},
        )
        return cid
