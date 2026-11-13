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
from .boundaries import ALLOWED_SKILL_IMPORTS, ASTSecurityAuditor, assert_safe_modification, audit_code_safety, is_protected_file
from .scout import CapabilityScout
from .synthesizer import ToolSynthesizer
from .types import AutoHealResult, CandidateSkill, CapabilityGap, DiagnosticReport, SkillQualityReport, TestExecutionResult


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

            if heal_res.status == "repaired" and heal_res.patched_digest and heal_res.repaired_code:
                current_code = heal_res.repaired_code
                repaired_candidate = CandidateSkill(
                    id=candidate.id,
                    name=candidate.name,
                    description=candidate.description,
                    code=heal_res.repaired_code,
                    test_cases=candidate.test_cases,
                    digest=heal_res.patched_digest,
                    version=candidate.version,
                    project_id=candidate.project_id,
                    permissions=candidate.permissions,
                )
                test_res = self.synthesizer.run_tests(repaired_candidate)
                if test_res.passed:
                    candidate = repaired_candidate
                    break

        # If candidate passed 100%, record into store if available
        if test_res.passed and self.store is not None:
            self._save_candidate(candidate, test_res)

        return gap, candidate, test_res

    def identify_existing_skills(self, gap: CapabilityGap) -> list[dict[str, Any]]:
        """Step 2 of Skill Forging lifecycle: check existing registered tools and active procedures."""
        matches: list[dict[str, Any]] = []
        target = gap.suggested_tool_name.lower().replace("-", "_")
        for tool_name in sorted(self.scout.registered_tools):
            if target in tool_name.lower() or tool_name.lower() in target:
                matches.append({"id": tool_name, "source": "builtin_registry", "version": 1})
        if self.store is not None:
            try:
                with self.store.connect() as db:
                    rows = db.execute(
                        "SELECT id, version, digest, invoked, failed FROM procedures WHERE active = 1"
                    ).fetchall()
                    for r in rows:
                        if target in r["id"].lower() or r["id"].lower() in target:
                            matches.append(dict(r) | {"source": "procedures_store"})
            except Exception:
                pass
        return matches

    def research_capability(self, gap: CapabilityGap) -> dict[str, Any]:
        """Step 3 of Skill Forging lifecycle: analyze missing capability requirements & existing coverage."""
        existing = self.identify_existing_skills(gap)
        return {
            "gap_id": gap.id,
            "suggested_tool_name": gap.suggested_tool_name,
            "missing_capability": gap.missing_capability,
            "existing_skills": existing,
            "action": "improve_existing" if existing else "generate_new",
            "allowed_imports": sorted(ALLOWED_SKILL_IMPORTS),
            "required_permissions": ["sandbox.execute"],
        }

    def validate_dependencies_and_permissions(self, candidate: CandidateSkill) -> tuple[bool, list[str], str | None]:
        """Step 5 of Skill Forging lifecycle: verify AST imports and permission boundaries."""
        import ast
        try:
            tree = ast.parse(candidate.code)
        except SyntaxError as exc:
            return False, [], f"SyntaxError: {exc}"
        auditor = ASTSecurityAuditor()
        auditor.visit(tree)
        if auditor.violations:
            return False, auditor.imported_modules, "; ".join(auditor.violations)
        disallowed_deps = [m for m in auditor.imported_modules if m not in ALLOWED_SKILL_IMPORTS]
        if disallowed_deps:
            return False, auditor.imported_modules, f"Unapproved dependencies: {', '.join(disallowed_deps)}"
        disallowed_perms = [p for p in candidate.permissions if p not in ("sandbox.execute", "text.transform")]
        if disallowed_perms:
            return False, auditor.imported_modules, f"Unapproved permissions: {', '.join(disallowed_perms)}"
        return True, sorted(set(auditor.imported_modules)), None

    def evaluate_quality(
        self, candidate: CandidateSkill, test_res: TestExecutionResult
    ) -> SkillQualityReport:
        """Steps 8-10 of Skill Forging lifecycle: security, performance, reliability & quality report."""
        is_safe, _ = audit_code_safety(candidate.code)
        deps_ok, deps, dep_err = self.validate_dependencies_and_permissions(candidate)
        pass_rate = (
            test_res.passed_cases / test_res.total_cases
            if test_res.total_cases > 0
            else 0.0
        )
        latency_penalty = min(0.25, max(0.0, (test_res.execution_time_ms - 500.0) / 2500.0))
        reliability = round(max(0.0, pass_rate - latency_penalty), 3) if (is_safe and deps_ok and test_res.passed) else 0.0
        ready = bool(test_res.passed and is_safe and deps_ok and pass_rate == 1.0)
        return SkillQualityReport(
            skill_id=candidate.id,
            version=candidate.version,
            digest=candidate.digest,
            functional_pass_rate=round(pass_rate, 3),
            security_audit_passed=bool(is_safe),
            dependencies_verified=bool(deps_ok),
            dependencies=deps,
            permissions=list(candidate.permissions),
            execution_latency_ms=round(test_res.execution_time_ms, 2),
            reliability_score=reliability,
            owner_approval_required=True,
            ready_for_promotion=ready,
            recommendation=(
                "Verified in sandbox; ready for owner approval and promotion."
                if ready
                else f"Promotion blocked: {dep_err or test_res.error_message or 'failed verification gates'}."
            ),
        )

    def promote_candidate(
        self, candidate_id: str, expected_digest: str, *, owner_approved: bool = True
    ) -> dict[str, Any]:
        """Promote a tested candidate into the active procedures registry after owner approval."""
        if not owner_approved:
            raise PermissionError("Owner approval is mandatory before promoting a synthesized skill.")
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

    def record_skill_execution(self, skill_id: str, *, success: bool, latency_ms: float = 0.0) -> dict[str, Any]:
        """Step 14 of Skill Forging lifecycle: monitor post-promotion skill performance and reliability."""
        if self.store is None:
            return {"skill_id": skill_id, "monitored": False}
        now = time.time()
        with self.store.connect() as db:
            row = db.execute(
                "SELECT version, invoked, failed FROM procedures WHERE id = ? AND active = 1",
                (skill_id,),
            ).fetchone()
            if not row:
                raise ValueError(f"Active skill '{skill_id}' not found.")
            version = row["version"]
            invoked = int(row["invoked"] or 0) + 1
            failed = int(row["failed"] or 0) + (0 if success else 1)
            db.execute(
                "UPDATE procedures SET invoked = ?, failed = ?, last_used = ? WHERE id = ? AND version = ?",
                (invoked, failed, now, skill_id, version),
            )
            self.store.event(
                "rsi.skill_monitored",
                skill_id,
                {"version": version, "success": success, "latency_ms": round(latency_ms, 2), "invoked": invoked, "failed": failed},
                db,
            )
        failure_rate = round(failed / invoked, 3) if invoked > 0 else 0.0
        return {
            "skill_id": skill_id,
            "version": version,
            "invoked": invoked,
            "failed": failed,
            "failure_rate": failure_rate,
            "healthy": failure_rate < 0.5,
        }

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
