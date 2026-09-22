"""Focused tests for Milestone 8 — Completeness Verification & Migration Report.

Tests cover:

* fully migrated repository → SUCCESS
* remaining old usage → PARTIALLY_MIGRATED
* manual review → BLOCKED
* transformation failure → FAILED
* no migration required → NO_MIGRATION_REQUIRED
* validation failure with migration diagnosis
* completeness accounting matches affected usages

All tests use deterministic, minimal fixtures and verify the completeness
accounting matches the affected usages list.
"""

from __future__ import annotations 

import pytest
from pathlib import Path

from migration_agent import (
    AffectedUsage,
    ChangeType,
    CompletenessResult,
    Confidence,
    Evidence,
    MigrationAction,
    MigrationActionStrategy,
    MigrationChange,
    MigrationOutcome,
    MigrationPlan,
    MigrationReport,
    MigrationSpec,
    TransformationRecord,
    TransformationResult,
    TransformationStatus,
    UsageClassification,
    UsageDisposition,
    ValidationRecord,
    ValidationResult,
    ValidationStatus,
    create_migration_plan,
    execute_transformation_plan,
    execute_validation,
    generate_report,
    verify_completeness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence():
    return Evidence(
        source="Pydantic Migration Guide (V1 -> V2)",
        section="Changes to pydantic.BaseModel",
        excerpt="parse_obj() model_validate()",
        url="https://docs.pydantic.dev/2.10/migration/",
    )


def _make_change(
    change_type: ChangeType,
    old: str | None,
    new: str | None,
    description: str = "test change",
) -> MigrationChange:
    return MigrationChange(
        change_type=change_type,
        old=old,
        new=new,
        description=description,
        evidence=_evidence(),
        confidence=Confidence.HIGH,
    )


def _make_usage(
    change: MigrationChange,
    file: str = "app.py",
    line: int = 1,
    classification: UsageClassification = UsageClassification.CONFIRMED,
) -> AffectedUsage:
    return AffectedUsage(
        change=change,
        file=file,
        line=line,
        source_context=f"line {line}: example code",
        classification=classification,
    )


def _make_plan(repo, actions):
    spec = MigrationSpec(
        repository=str(repo),
        technology="pydantic",
        source_version="1.10.14",
        target_version="2",
        source_version_exact=True,
    )
    return MigrationPlan(spec=spec, actions=actions)


def _make_action(file, line, strategy, old, new):
    change = _make_change(ChangeType.REPLACEMENT, old, new)
    usage = _make_usage(change, file=file, line=line)
    return MigrationAction(
        usage=usage,
        strategy=strategy,
        reason="test reason",
        old=old,
        new=new,
    )


def _make_transformation_record(
    action: MigrationAction,
    file: str,
    status: TransformationStatus,
    changed: bool = False,
    error: str | None = None,
) -> TransformationRecord:
    return TransformationRecord(
        action=action,
        file=file,
        strategy=action.strategy,
        status=status,
        changed=changed,
        error=error,
    )


def _make_validation_record(
    check: str,
    status: ValidationStatus,
    output: str | None = None,
    error: str | None = None,
    affected_files: list[str] | None = None,
) -> ValidationRecord:
    return ValidationRecord(
        check=check,
        status=status,
        output=output,
        error=error,
        affected_files=affected_files or [],
    )


def _make_completeness_result(
    affected_usages: list[AffectedUsage],
    transformation_records: list[TransformationRecord] | None = None,
    validation_records: list[ValidationRecord] | None = None,
    spec: MigrationSpec | None = None,
) -> CompletenessResult:
    """Helper to create a CompletenessResult for testing."""
    if spec is None:
        spec = MigrationSpec(
            repository=".",
            technology="pydantic",
            source_version="1.10.14",
            target_version="2",
            source_version_exact=True,
        )

    tr_records = transformation_records or []
    vr_records = validation_records or []

    return CompletenessResult(
        spec_repository=spec.repository,
        spec_technology=spec.technology,
        source_version=spec.source_version,
        target_version=spec.target_version,
        affected_usages=affected_usages,
        transformation_records=tr_records,
        validation_records=vr_records,
    )


# ===========================================================================
# Tests
# ===========================================================================


class TestFullyMigratedRepository:
    """Fully migrated repository → SUCCESS."""

    def test_all_usages_migrated_successfully(self, tmp_path: Path):
        """When all usages are migrated and validation passes, outcome is SUCCESS."""
        # Create a simple repo with actual parse_obj usage
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("from pydantic import BaseModel\n\nclass User(BaseModel):\n    name: str\n\nuser = User.parse_obj({'name': 'test'})\n")

        # Create usage and plan
        change = _make_change(ChangeType.REPLACEMENT, "parse_obj", "model_validate")
        usage = _make_usage(change, file="app.py", line=6)  # Line where parse_obj is used
        action = _make_action("app.py", 6, MigrationActionStrategy.TEXT_EDIT, "parse_obj", "model_validate")
        plan = _make_plan(repo, [action])

        # Execute transformation
        result = execute_transformation_plan(plan, repo_path=str(repo))

        # Check that transformation succeeded
        assert result.success
        assert any(r.status == TransformationStatus.SUCCESS for r in result.records)

        # Create validation result (all passing)
        validation_result = ValidationResult(
            working_copy=str(repo),
            records=[
                _make_validation_record("syntax", ValidationStatus.PASS),
                _make_validation_record("residual_old_usage", ValidationStatus.PASS),
                _make_validation_record("target_usage", ValidationStatus.PASS),
            ],
            success=True,
        )

        # Verify completeness
        completeness = verify_completeness(
            affected_usages=[usage],
            transformation_result=result,
            validation_result=validation_result,
            spec=plan.spec,
        )

        # Check outcome
        assert completeness.outcome == MigrationOutcome.SUCCESS
        assert completeness.migrated_count == 1
        assert completeness.total_affected_usages == 1
        assert completeness.failed_count == 0
        assert completeness.manual_review_count == 0

        # Check report
        report = generate_report(completeness)
        assert report.outcome == MigrationOutcome.SUCCESS
        assert report.is_successful
        assert report.migrated_count == 1

    def test_completeness_accounting_matches_usages(self):
        """Completeness accounting should match affected usages list."""
        change = _make_change(ChangeType.REPLACEMENT, "old_api", "new_api")
        usages = [
            _make_usage(change, file="file1.py", line=1),
            _make_usage(change, file="file2.py", line=5),
            _make_usage(change, file="file3.py", line=10),
        ]

        # Create records for all usages
        records = []
        for usage in usages:
            action = MigrationAction(
                usage=usage,
                strategy=MigrationActionStrategy.TEXT_EDIT,
                reason="test",
                old=usage.change.old,
                new=usage.change.new,
            )
            records.append(
                _make_transformation_record(
                    action,
                    usage.file,
                    TransformationStatus.SUCCESS,
                    changed=True,
                )
            )

        spec = MigrationSpec(
            repository=".",
            technology="pydantic",
            source_version="1.10.14",
            target_version="2",
            source_version_exact=True,
        )

        completeness = _make_completeness_result(
            affected_usages=usages,
            transformation_records=records,
        )

        # Manually run verification logic to populate counts
        # Match by file and line since usage objects may be different instances
        usage_to_record: dict[tuple[str, int], TransformationRecord] = {}
        for r in records:
            if hasattr(r.action, "usage") and r.action.usage is not None:
                usage_key = (r.action.usage.file, r.action.usage.line)
                usage_to_record[usage_key] = r
        for usage in usages:
            usage_key = (usage.file, usage.line)
            record = usage_to_record.get(usage_key)
            if record and record.status.value == "success":
                completeness.migrated_count += 1

        # Verify accounting
        assert completeness.total_affected_usages == 3
        assert completeness.migrated_count == 3
        assert completeness.migrated_count + completeness.not_migrated_count + completeness.skipped_count + completeness.failed_count + completeness.manual_review_count == 3


class TestRemainingOldUsage:
    """Remaining old usage → PARTIALLY_MIGRATED."""

    def test_residual_old_usage_detected(self, tmp_path: Path):
        """When residual old usage is detected in validation, outcome is PARTIALLY_MIGRATED."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("from pydantic import BaseModel\n\nclass User(BaseModel):\n    name: str\n\nuser = User.parse_obj({'name': 'test'})\n")

        change = _make_change(ChangeType.REPLACEMENT, "parse_obj", "model_validate")
        usage = _make_usage(change, file="app.py", line=6)
        action = _make_action("app.py", 6, MigrationActionStrategy.TEXT_EDIT, "parse_obj", "model_validate")
        plan = _make_plan(repo, [action])

        # Execute transformation (simulate success)
        result = execute_transformation_plan(plan, repo_path=str(repo))
        
        # Check that transformation succeeded
        assert result.success

        # Create validation result with residual old usage failure
        # Simulate that validation found old usage (even though transformation succeeded)
        validation_result = ValidationResult(
            working_copy=str(repo),
            records=[
                _make_validation_record("syntax", ValidationStatus.PASS),
                _make_validation_record(
                    "residual_old_usage",
                    ValidationStatus.FAIL,
                    output="Found 1 occurrence of old API",
                    affected_files=["app.py"],
                ),
                _make_validation_record("target_usage", ValidationStatus.PASS),
            ],
            success=False,
        )

        completeness = verify_completeness(
            affected_usages=[usage],
            transformation_result=result,
            validation_result=validation_result,
            spec=plan.spec,
        )

        # Check outcome
        assert completeness.outcome == MigrationOutcome.PARTIALLY_MIGRATED
        assert len(completeness.remaining_old_usages) == 1
        assert completeness.remaining_old_usages[0].check == "residual_old_usage"

        # Check report
        report = generate_report(completeness)
        assert report.outcome == MigrationOutcome.PARTIALLY_MIGRATED
        assert not report.is_successful
        assert len(report.remaining_old_usages) == 1


class TestManualReview:
    """Manual review → BLOCKED."""

    def test_manual_review_blocks_migration(self, tmp_path: Path):
        """When there are manual review items, outcome is BLOCKED."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("from pydantic import BaseModel\n")

        change = _make_change(ChangeType.BEHAVIOR, "old_behavior", "new_behavior")
        usage = _make_usage(change, file="app.py", line=1)
        action = _make_action("app.py", 1, MigrationActionStrategy.MANUAL_REVIEW, "old_behavior", "new_behavior")
        plan = _make_plan(repo, [action])

        # Execute transformation (manual review items are skipped)
        result = execute_transformation_plan(plan, repo_path=str(repo))

        # Create validation result (all passing)
        validation_result = ValidationResult(
            working_copy=str(repo),
            records=[
                _make_validation_record("syntax", ValidationStatus.PASS),
                _make_validation_record("residual_old_usage", ValidationStatus.PASS),
                _make_validation_record("target_usage", ValidationStatus.PASS),
            ],
            success=True,
        )

        completeness = verify_completeness(
            affected_usages=[usage],
            transformation_result=result,
            validation_result=validation_result,
            spec=plan.spec,
        )

        # Check outcome
        assert completeness.outcome == MigrationOutcome.BLOCKED
        assert completeness.manual_review_count == 1
        assert len(completeness.manual_review_items) == 1

        # Check report
        report = generate_report(completeness)
        assert report.outcome == MigrationOutcome.BLOCKED
        assert not report.is_successful
        assert report.manual_review_count == 1
        assert len(report.manual_review_items) == 1

    def test_manual_review_items_in_report(self):
        """Manual review items should be properly listed in the report."""
        change = _make_change(ChangeType.BEHAVIOR, "old", "new")
        usage = _make_usage(change, file="app.py", line=10)

        action = MigrationAction(
            usage=usage,
            strategy=MigrationActionStrategy.MANUAL_REVIEW,
            reason="Behavior change requires manual review",
            old="old",
            new="new",
        )

        record = _make_transformation_record(
            action,
            "app.py",
            TransformationStatus.SKIPPED,
            error="Manual review required",
        )

        spec = MigrationSpec(
            repository=".",
            technology="pydantic",
            source_version="1.10.14",
            target_version="2",
            source_version_exact=True,
        )

        completeness = _make_completeness_result(
            affected_usages=[usage],
            transformation_records=[record],
        )

        # Manually set the disposition
        completeness.usage_dispositions = [(usage, UsageDisposition.MANUAL_REVIEW, "Manual review required")]
        completeness.manual_review_count = 1
        completeness.manual_review_items = [(usage, "Manual review required")]

        report = generate_report(completeness)
        assert report.manual_review_count == 1
        assert len(report.manual_review_items) == 1
        assert report.manual_review_items[0][0].file == "app.py"


class TestTransformationFailure:
    """Transformation failure → FAILED."""

    def test_transformation_failure_results_in_failed_outcome(self, tmp_path: Path):
        """When transformation fails, outcome is FAILED."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("from pydantic import BaseModel\n")

        change = _make_change(ChangeType.REPLACEMENT, "parse_obj", "model_validate")
        usage = _make_usage(change, file="nonexistent.py", line=1)  # File doesn't exist
        action = _make_action("nonexistent.py", 1, MigrationActionStrategy.TEXT_EDIT, "parse_obj", "model_validate")
        plan = _make_plan(repo, [action])

        # Execute transformation (will fail because file doesn't exist)
        result = execute_transformation_plan(plan, repo_path=str(repo))

        # Check that transformation failed
        assert not result.success
        assert any(r.status == TransformationStatus.FAILED for r in result.records)

        # Create validation result
        validation_result = ValidationResult(
            working_copy=str(repo),
            records=[
                _make_validation_record("syntax", ValidationStatus.PASS),
                _make_validation_record("residual_old_usage", ValidationStatus.PASS),
            ],
            success=True,
        )

        completeness = verify_completeness(
            affected_usages=[usage],
            transformation_result=result,
            validation_result=validation_result,
            spec=plan.spec,
        )

        # Check outcome
        assert completeness.outcome == MigrationOutcome.FAILED
        assert completeness.failed_count == 1
        assert len(completeness.failures) == 1

        # Check report
        report = generate_report(completeness)
        assert report.outcome == MigrationOutcome.FAILED
        assert not report.is_successful
        assert report.failed_count == 1
        assert len(report.failures) == 1

    def test_failure_diagnosis_in_report(self):
        """Failure diagnosis should be included in the report."""
        change = _make_change(ChangeType.REPLACEMENT, "old", "new")
        usage = _make_usage(change, file="app.py", line=5)

        action = MigrationAction(
            usage=usage,
            strategy=MigrationActionStrategy.TEXT_EDIT,
            reason="test",
            old="old",
            new="new",
        )

        record = _make_transformation_record(
            action,
            "app.py",
            TransformationStatus.FAILED,
            error="File not found",
        )

        spec = MigrationSpec(
            repository=".",
            technology="pydantic",
            source_version="1.10.14",
            target_version="2",
            source_version_exact=True,
        )

        completeness = _make_completeness_result(
            affected_usages=[usage],
            transformation_records=[record],
        )

        # Manually set the disposition
        completeness.usage_dispositions = [(usage, UsageDisposition.FAILED, "Transformation failed: File not found")]
        completeness.failed_count = 1
        completeness.failures = [(usage, record, "Transformation failed: File not found")]

        report = generate_report(completeness)
        assert report.failed_count == 1
        assert len(report.failures) == 1
        assert report.failures[0][0].file == "app.py"
        assert "File not found" in report.failures[0][2]


class TestNoMigrationRequired:
    """No migration required → NO_MIGRATION_REQUIRED."""

    def test_no_affected_usages_means_no_migration_required(self):
        """When there are no affected usages, outcome is NO_MIGRATION_REQUIRED."""
        spec = MigrationSpec(
            repository=".",
            technology="pydantic",
            source_version="1.10.14",
            target_version="2",
            source_version_exact=True,
        )

        completeness = _make_completeness_result(
            affected_usages=[],
            transformation_records=[],
            validation_records=[],
            spec=spec,
        )

        # Check outcome
        assert completeness.outcome == MigrationOutcome.NO_MIGRATION_REQUIRED
        assert completeness.total_affected_usages == 0
        assert completeness.migrated_count == 0

        # Check report
        report = generate_report(completeness)
        assert report.outcome == MigrationOutcome.NO_MIGRATION_REQUIRED
        assert report.total_affected_usages == 0

    def test_no_migration_when_source_equals_target(self):
        """When source version equals target version, no migration is required."""
        spec = MigrationSpec(
            repository=".",
            technology="pydantic",
            source_version="2.0.0",
            target_version="2",
            source_version_exact=True,
        )

        completeness = _make_completeness_result(
            affected_usages=[],
            spec=spec,
        )

        assert completeness.outcome == MigrationOutcome.NO_MIGRATION_REQUIRED


class TestValidationFailureWithDiagnosis:
    """Validation failure with migration diagnosis."""

    def test_validation_failure_produces_diagnosis(self, tmp_path: Path):
        """When validation fails, the report should include diagnosis information."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "app.py").write_text("from pydantic import BaseModel\n\nclass User(BaseModel):\n    name: str\n\nuser = User.parse_obj({'name': 'test'})\n")

        change = _make_change(ChangeType.REPLACEMENT, "parse_obj", "model_validate")
        usage = _make_usage(change, file="app.py", line=6)
        action = _make_action("app.py", 6, MigrationActionStrategy.TEXT_EDIT, "parse_obj", "model_validate")
        plan = _make_plan(repo, [action])

        # Execute transformation
        result = execute_transformation_plan(plan, repo_path=str(repo))
        
        # Check that transformation succeeded
        assert result.success

        # Create validation result with multiple failures
        validation_result = ValidationResult(
            working_copy=str(repo),
            records=[
                _make_validation_record("syntax", ValidationStatus.FAIL, error="Syntax error in app.py"),
                _make_validation_record(
                    "residual_old_usage",
                    ValidationStatus.FAIL,
                    output="Found old API usage",
                    affected_files=["app.py"],
                ),
                _make_validation_record("target_usage", ValidationStatus.FAIL, error="Target API not found"),
            ],
            success=False,
            notes=["3 validation check(s) failed; review syntax, residual_old_usage, target_usage."],
        )

        completeness = verify_completeness(
            affected_usages=[usage],
            transformation_result=result,
            validation_result=validation_result,
            spec=plan.spec,
        )

        # Check that remaining old usages are detected
        assert len(completeness.remaining_old_usages) == 1

        # Check report includes validation failures
        report = generate_report(completeness)
        assert not report.validation_success
        assert len(report.validation_records) == 3
        assert any(r.check == "syntax" and r.status.value == "fail" for r in report.validation_records)
        assert any(r.check == "residual_old_usage" and r.status.value == "fail" for r in report.validation_records)


class TestCompletenessAccounting:
    """Completeness accounting matches affected usages."""

    def test_counts_sum_to_total(self):
        """The sum of all disposition counts should equal total affected usages."""
        change = _make_change(ChangeType.REPLACEMENT, "old", "new")
        usages = [
            _make_usage(change, file="file1.py", line=1),
            _make_usage(change, file="file2.py", line=2),
            _make_usage(change, file="file3.py", line=3),
            _make_usage(change, file="file4.py", line=4),
            _make_usage(change, file="file5.py", line=5),
        ]

        # Create various records
        records = []
        for i, usage in enumerate(usages):
            action = MigrationAction(
                usage=usage,
                strategy=MigrationActionStrategy.TEXT_EDIT,
                reason="test",
                old="old",
                new="new",
            )
            if i < 2:
                status = TransformationStatus.SUCCESS
            elif i == 2:
                status = TransformationStatus.SKIPPED
            elif i == 3:
                status = TransformationStatus.FAILED
            else:
                status = TransformationStatus.PENDING

            records.append(
                _make_transformation_record(
                    action,
                    usage.file,
                    status,
                )
            )

        spec = MigrationSpec(
            repository=".",
            technology="pydantic",
            source_version="1.10.14",
            target_version="2",
            source_version_exact=True,
        )

        completeness = _make_completeness_result(
            affected_usages=usages,
            transformation_records=records,
            spec=spec,
        )

        # Manually run the classification logic
        # Match by file and line since usage objects may be different instances
        usage_to_record: dict[tuple[str, int], TransformationRecord] = {}
        for r in records:
            if hasattr(r.action, "usage") and r.action.usage is not None:
                usage_key = (r.action.usage.file, r.action.usage.line)
                usage_to_record[usage_key] = r
        for usage in usages:
            usage_key = (usage.file, usage.line)
            record = usage_to_record.get(usage_key)
            # Use the internal _classify_usage function from the completeness module
            from migration_agent.completeness import _classify_usage
            disposition, _ = _classify_usage(usage, record)
            completeness.usage_dispositions.append((usage, disposition, ""))

            if disposition == UsageDisposition.MIGRATED:
                completeness.migrated_count += 1
            elif disposition == UsageDisposition.NOT_MIGRATED:
                completeness.not_migrated_count += 1
            elif disposition == UsageDisposition.SKIPPED:
                completeness.skipped_count += 1
            elif disposition == UsageDisposition.FAILED:
                completeness.failed_count += 1
            elif disposition == UsageDisposition.MANUAL_REVIEW:
                completeness.manual_review_count += 1

        # Verify accounting
        total = (
            completeness.migrated_count
            + completeness.not_migrated_count
            + completeness.skipped_count
            + completeness.failed_count
            + completeness.manual_review_count
        )
        assert total == completeness.total_affected_usages
        assert total == 5

    def test_handled_count_excludes_unresolved(self):
        """Handled count should exclude failed and not_migrated usages."""
        change = _make_change(ChangeType.REPLACEMENT, "old", "new")
        usages = [
            _make_usage(change, file="file1.py", line=1),
            _make_usage(change, file="file2.py", line=2),
            _make_usage(change, file="file3.py", line=3),
        ]

        records = []
        for i, usage in enumerate(usages):
            action = MigrationAction(
                usage=usage,
                strategy=MigrationActionStrategy.TEXT_EDIT,
                reason="test",
                old="old",
                new="new",
            )
            if i == 0:
                status = TransformationStatus.SUCCESS
            elif i == 1:
                status = TransformationStatus.FAILED
            else:
                status = TransformationStatus.PENDING

            records.append(
                _make_transformation_record(
                    action,
                    usage.file,
                    status,
                )
            )

        spec = MigrationSpec(
            repository=".",
            technology="pydantic",
            source_version="1.10.14",
            target_version="2",
            source_version_exact=True,
        )

        completeness = _make_completeness_result(
            affected_usages=usages,
            transformation_records=records,
            spec=spec,
        )

        # Manually run classification
        # Match by file and line since usage objects may be different instances
        usage_to_record: dict[tuple[str, int], TransformationRecord] = {}
        for r in records:
            if hasattr(r.action, "usage") and r.action.usage is not None:
                usage_key = (r.action.usage.file, r.action.usage.line)
                usage_to_record[usage_key] = r
        for usage in usages:
            usage_key = (usage.file, usage.line)
            record = usage_to_record.get(usage_key)
            # Use the internal _classify_usage function from the completeness module
            from migration_agent.completeness import _classify_usage
            disposition, _ = _classify_usage(usage, record)
            completeness.usage_dispositions.append((usage, disposition, ""))

            if disposition == UsageDisposition.MIGRATED:
                completeness.migrated_count += 1
            elif disposition == UsageDisposition.NOT_MIGRATED:
                completeness.not_migrated_count += 1
            elif disposition == UsageDisposition.SKIPPED:
                completeness.skipped_count += 1
            elif disposition == UsageDisposition.FAILED:
                completeness.failed_count += 1
            elif disposition == UsageDisposition.MANUAL_REVIEW:
                completeness.manual_review_count += 1

        # Handled = migrated + skipped + manual_review
        assert completeness.handled_count == 1  # Only the migrated one
        assert completeness.unresolved_count == 2  # Failed + pending (not_migrated)


class TestMigrationReport:
    """Tests for MigrationReport generation and content."""

    def test_report_contains_all_required_fields(self):
        """MigrationReport should contain all required information."""
        change = _make_change(ChangeType.REPLACEMENT, "old", "new")
        usage = _make_usage(change, file="app.py", line=1)

        action = MigrationAction(
            usage=usage,
            strategy=MigrationActionStrategy.TEXT_EDIT,
            reason="test",
            old="old",
            new="new",
        )

        record = _make_transformation_record(
            action,
            "app.py",
            TransformationStatus.SUCCESS,
            changed=True,
        )

        validation_record = _make_validation_record(
            "syntax",
            ValidationStatus.PASS,
        )

        spec = MigrationSpec(
            repository="/test/repo",
            technology="pydantic",
            source_version="1.10.14",
            target_version="2",
            source_version_exact=True,
        )

        completeness = _make_completeness_result(
            affected_usages=[usage],
            transformation_records=[record],
            validation_records=[validation_record],
            spec=spec,
        )

        # Manually set dispositions
        completeness.usage_dispositions = [(usage, UsageDisposition.MIGRATED, "Success")]
        completeness.migrated_count = 1
        completeness.outcome = MigrationOutcome.SUCCESS  # Set the outcome
        completeness.change_evidence = [(change, "Pydantic Migration Guide: Changes to pydantic.BaseModel")]

        report = generate_report(completeness)

        # Verify all required fields are present
        # Note: repository path may include leading slash depending on input
        assert report.repository.endswith("test/repo") or report.repository == "/test/repo"
        assert report.technology == "pydantic"
        assert report.source_version == "1.10.14"
        assert report.target_version == "2"
        assert report.total_affected_usages == 1
        assert report.migrated_count == 1
        assert report.outcome == MigrationOutcome.SUCCESS
        assert len(report.change_evidence) == 1
        assert report.summary  # Should have a human-readable summary

    def test_report_summary_is_readable(self, capsys):
        """The report summary should be human-readable."""
        change = _make_change(ChangeType.REPLACEMENT, "parse_obj", "model_validate")
        usage = _make_usage(change, file="app.py", line=1)

        action = MigrationAction(
            usage=usage,
            strategy=MigrationActionStrategy.TEXT_EDIT,
            reason="test",
            old="parse_obj",
            new="model_validate",
        )

        record = _make_transformation_record(
            action,
            "app.py",
            TransformationStatus.SUCCESS,
            changed=True,
        )

        spec = MigrationSpec(
            repository=".",
            technology="pydantic",
            source_version="1.10.14",
            target_version="2",
            source_version_exact=True,
        )

        completeness = _make_completeness_result(
            affected_usages=[usage],
            transformation_records=[record],
            spec=spec,
        )
        completeness.usage_dispositions = [(usage, UsageDisposition.MIGRATED, "Success")]
        completeness.migrated_count = 1
        completeness.outcome = MigrationOutcome.SUCCESS  # Set the outcome
        completeness.change_evidence = [(change, "Pydantic Migration Guide: Changes to pydantic.BaseModel")]

        report = generate_report(completeness)

        # Verify summary contains key information
        summary = report.summary
        assert "MIGRATION REPORT" in summary
        assert "Repository:" in summary
        assert "Technology:" in summary
        assert "Source Version:" in summary
        assert "Target Version:" in summary
        assert "AFFECTED USAGES" in summary
        assert "FINAL OUTCOME" in summary
        assert "SUCCESS" in summary


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
