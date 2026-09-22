"""Migration reporting (Milestone 8).

Generates a comprehensive MigrationReport from a CompletenessResult,
providing a detailed summary of the migration process including:

* source and target versions
* migration changes used
* affected usage counts
* transformation summary
* validation summary
* unresolved usages
* manual-review items
* failures and their diagnoses
* final outcome
* evidence/references for migration changes
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .completeness import (
    CompletenessResult,
    MigrationOutcome,
    UsageDisposition,
)
from .models import (
    AffectedUsage,
    MigrationChange,
    TransformationRecord,
    ValidationRecord,
)


@dataclass
class MigrationReport:
    """Comprehensive report of a migration process.

    Contains all relevant information about the migration including
    the spec, affected usages, transformation results, validation
    results, and the final outcome.
    """

    # Migration specification
    repository: str
    technology: str
    source_version: str | None
    target_version: str

    # Migration changes (with evidence)
    changes: list[MigrationChange] = field(default_factory=list)
    change_evidence: list[tuple[MigrationChange, str]] = field(default_factory=list)

    # Affected usages
    total_affected_usages: int = 0
    usage_dispositions: list[tuple[AffectedUsage, UsageDisposition, str]] = field(
        default_factory=list
    )

    # Counts by disposition
    migrated_count: int = 0
    not_migrated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    manual_review_count: int = 0

    # Transformation summary
    transformation_success: bool = False
    transformation_notes: list[str] = field(default_factory=list)
    transformation_records: list[TransformationRecord] = field(default_factory=list)

    # Validation summary
    validation_success: bool = False
    validation_notes: list[str] = field(default_factory=list)
    validation_records: list[ValidationRecord] = field(default_factory=list)

    # Remaining issues
    remaining_old_usages: list[ValidationRecord] = field(default_factory=list)
    unresolved_usages: list[tuple[AffectedUsage, str]] = field(default_factory=list)
    manual_review_items: list[tuple[AffectedUsage, str]] = field(default_factory=list)
    failures: list[tuple[AffectedUsage, TransformationRecord | None, str]] = field(
        default_factory=list
    )

    # Overall outcome
    outcome: MigrationOutcome = MigrationOutcome.NO_MIGRATION_REQUIRED

    # Human-readable summary
    summary: str = ""

    @property
    def is_successful(self) -> bool:
        """Whether the migration was fully successful."""
        return self.outcome == MigrationOutcome.SUCCESS

    @property
    def has_issues(self) -> bool:
        """Whether the migration has any unresolved issues."""
        return (
            self.failed_count > 0
            or self.manual_review_count > 0
            or self.not_migrated_count > 0
            or len(self.remaining_old_usages) > 0
        )


def generate_report(completeness_result: CompletenessResult) -> MigrationReport:
    """Generate a comprehensive MigrationReport from a CompletenessResult.

    :param completeness_result: The result of completeness verification.
    :return: A detailed MigrationReport.
    """
    report = MigrationReport(
        repository=completeness_result.spec_repository,
        technology=completeness_result.spec_technology,
        source_version=completeness_result.source_version,
        target_version=completeness_result.target_version,
        total_affected_usages=completeness_result.total_affected_usages,
        usage_dispositions=completeness_result.usage_dispositions,
        migrated_count=completeness_result.migrated_count,
        not_migrated_count=completeness_result.not_migrated_count,
        skipped_count=completeness_result.skipped_count,
        failed_count=completeness_result.failed_count,
        manual_review_count=completeness_result.manual_review_count,
        remaining_old_usages=completeness_result.remaining_old_usages,
        manual_review_items=completeness_result.manual_review_items,
        failures=completeness_result.failures,
        outcome=completeness_result.outcome,
        change_evidence=completeness_result.change_evidence,
    )

    # Extract transformation and validation info
    records = completeness_result.transformation_records
    if records:
        report.transformation_records = records
        report.transformation_success = all(
            r.status.value == "success" if hasattr(r.status, 'value') else r.status == "success"
            for r in records
        )
        report.transformation_notes = [
            f"Total actions: {len(records)}",
            f"Successful: {sum(1 for r in records if (r.status.value if hasattr(r.status, 'value') else r.status) == 'success')}",
            f"Skipped: {sum(1 for r in records if (r.status.value if hasattr(r.status, 'value') else r.status) == 'skipped')}",
            f"Failed: {sum(1 for r in records if (r.status.value if hasattr(r.status, 'value') else r.status) == 'failed')}",
            f"Pending: {sum(1 for r in records if (r.status.value if hasattr(r.status, 'value') else r.status) == 'pending')}",
        ]

    # Extract validation info
    validation_records = completeness_result.validation_records
    if validation_records:
        report.validation_records = validation_records
        report.validation_success = all(
            r.status.value == "pass" if hasattr(r.status, 'value') else r.status == "pass"
            for r in validation_records
        )
        report.validation_notes = [
            f"Total checks: {len(validation_records)}",
            f"Passed: {sum(1 for r in validation_records if (r.status.value if hasattr(r.status, 'value') else r.status) == 'pass')}",
            f"Failed: {sum(1 for r in validation_records if (r.status.value if hasattr(r.status, 'value') else r.status) == 'fail')}",
            f"Skipped: {sum(1 for r in validation_records if (r.status.value if hasattr(r.status, 'value') else r.status) == 'skipped')}",
        ]

    # Build unresolved usages list
    for usage, disposition, reason in completeness_result.usage_dispositions:
        if disposition in (UsageDisposition.NOT_MIGRATED, UsageDisposition.FAILED):
            report.unresolved_usages.append((usage, reason))

    # Generate human-readable summary
    report.summary = _generate_summary(report)

    return report


def _generate_summary(report: MigrationReport) -> str:
    """Generate a human-readable summary of the migration report."""
    lines = []

    # Header
    lines.append("=" * 70)
    lines.append("MIGRATION REPORT")
    lines.append("=" * 70)
    lines.append("")

    # Migration info
    lines.append("MIGRATION SPECIFICATION")
    lines.append("-" * 40)
    lines.append(f"Repository: {report.repository}")
    lines.append(f"Technology: {report.technology}")
    lines.append(f"Source Version: {report.source_version or 'unknown'}")
    lines.append(f"Target Version: {report.target_version}")
    lines.append("")

    # Changes
    if report.changes:
        lines.append("MIGRATION CHANGES")
        lines.append("-" * 40)
        for i, change in enumerate(report.changes, 1):
            lines.append(f"{i}. {change.description}")
            if change.evidence:
                lines.append(f"   Evidence: {change.evidence.source}")
                lines.append(f"   Section: {change.evidence.section}")
                if change.evidence.excerpt:
                    lines.append(f"   Excerpt: {change.evidence.excerpt[:100]}...")
        lines.append("")

    # Usage summary
    lines.append("AFFECTED USAGES")
    lines.append("-" * 40)
    lines.append(f"Total affected usages: {report.total_affected_usages}")
    lines.append(f"  - Migrated: {report.migrated_count}")
    lines.append(f"  - Not migrated: {report.not_migrated_count}")
    lines.append(f"  - Skipped: {report.skipped_count}")
    lines.append(f"  - Failed: {report.failed_count}")
    lines.append(f"  - Manual review: {report.manual_review_count}")
    lines.append("")

    # Transformation summary
    if report.transformation_records:
        lines.append("TRANSFORMATION SUMMARY")
        lines.append("-" * 40)
        for note in report.transformation_notes:
            lines.append(note)
        lines.append(f"Overall: {'SUCCESS' if report.transformation_success else 'FAILED'}")
        lines.append("")

    # Validation summary
    if report.validation_records:
        lines.append("VALIDATION SUMMARY")
        lines.append("-" * 40)
        for note in report.validation_notes:
            lines.append(note)
        lines.append(f"Overall: {'PASSED' if report.validation_success else 'FAILED'}")
        lines.append("")

    # Remaining issues
    if report.remaining_old_usages:
        lines.append("REMAINING OLD API USAGES")
        lines.append("-" * 40)
        for record in report.remaining_old_usages:
            lines.append(f"- {record.check}: {record.output or record.error or 'failed'}")
        lines.append("")

    if report.unresolved_usages:
        lines.append("UNRESOLVED USAGES")
        lines.append("-" * 40)
        for usage, reason in report.unresolved_usages:
            lines.append(f"- {usage.file}:{usage.line} - {reason}")
        lines.append("")

    if report.manual_review_items:
        lines.append("MANUAL REVIEW ITEMS")
        lines.append("-" * 40)
        for usage, reason in report.manual_review_items:
            lines.append(f"- {usage.file}:{usage.line} - {reason}")
        lines.append("")

    if report.failures:
        lines.append("FAILURES AND DIAGNOSES")
        lines.append("-" * 40)
        for usage, record, diagnosis in report.failures:
            lines.append(f"- {usage.file}:{usage.line}")
            lines.append(f"  Diagnosis: {diagnosis}")
            if record and record.error:
                lines.append(f"  Error: {record.error}")
        lines.append("")

    # Final outcome
    lines.append("FINAL OUTCOME")
    lines.append("-" * 40)
    lines.append(f"Outcome: {report.outcome.value.upper()}")
    lines.append("")

    # Change evidence
    if report.change_evidence:
        lines.append("CHANGE EVIDENCE")
        lines.append("-" * 40)
        for change, evidence_ref in report.change_evidence:
            lines.append(f"- {change.description}")
            lines.append(f"  Reference: {evidence_ref}")
        lines.append("")

    lines.append("=" * 70)

    return "\n".join(lines)
