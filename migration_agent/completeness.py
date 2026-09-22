"""Completeness verification for migration results (Milestone 8).

Pipeline::

    AffectedUsages + TransformationResult + ValidationResult
        |
        v
    CompletenessVerification (this module)
        |
        v
    CompletenessResult -> MigrationReport

This module verifies whether every discovered affected usage was handled,
detects remaining old API usage using existing validation results, and
determines an overall migration outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .models import (
    AffectedUsage,
    MigrationChange,
    TransformationRecord,
    ValidationRecord,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UsageDisposition(Enum):
    """How a single affected usage was handled during migration."""

    MIGRATED = "migrated"          # transformed successfully
    NOT_MIGRATED = "not_migrated"  # planned but not transformed (no action taken)
    SKIPPED = "skipped"            # intentionally skipped (NO_TRANSFORMATION)
    FAILED = "failed"              # transformation attempt failed
    MANUAL_REVIEW = "manual_review"  # requires human intervention


class MigrationOutcome(Enum):
    """Overall outcome of the migration process."""

    SUCCESS = "success"                # all usages migrated, validation passed
    PARTIALLY_MIGRATED = "partially_migrated"  # some usages handled, some remain
    BLOCKED = "blocked"                # migration blocked by manual review items
    FAILED = "failed"                  # transformation or validation failed
    NO_MIGRATION_REQUIRED = "no_migration_required"  # no changes needed


# ---------------------------------------------------------------------------
# CompletenessResult
# ---------------------------------------------------------------------------


@dataclass
class CompletenessResult:
    """Result of completeness verification for a migration.

    Aggregates information from affected usages, transformation results,
    and validation results to determine what was handled and what remains.
    """

    spec_repository: str
    spec_technology: str
    source_version: str | None
    target_version: str

    affected_usages: list[AffectedUsage]
    transformation_records: list[TransformationRecord]
    validation_records: list[ValidationRecord]

    # Per-usage disposition
    usage_dispositions: list[tuple[AffectedUsage, UsageDisposition, str]] = field(
        default_factory=list
    )

    # Counts
    migrated_count: int = 0
    not_migrated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    manual_review_count: int = 0

    # Remaining old API usages detected via validation
    remaining_old_usages: list[ValidationRecord] = field(default_factory=list)

    # Items requiring manual review
    manual_review_items: list[tuple[AffectedUsage, str]] = field(default_factory=list)

    # Failures and their diagnoses
    failures: list[tuple[AffectedUsage, TransformationRecord | None, str]] = field(
        default_factory=list
    )

    # Overall outcome
    outcome: MigrationOutcome = MigrationOutcome.NO_MIGRATION_REQUIRED

    # Evidence references for migration changes
    change_evidence: list[tuple[MigrationChange, str]] = field(default_factory=list)

    @property
    def total_affected_usages(self) -> int:
        """Total number of affected usages discovered."""
        return len(self.affected_usages)

    @property
    def handled_count(self) -> int:
        """Count of usages that were migrated, skipped, or pending manual review."""
        return (
            self.migrated_count
            + self.skipped_count
            + self.manual_review_count
        )

    @property
    def unresolved_count(self) -> int:
        """Count of usages not yet resolved (failed + not_migrated)."""
        return self.failed_count + self.not_migrated_count


# ---------------------------------------------------------------------------
# Completeness verification
# ---------------------------------------------------------------------------


def verify_completeness(
    affected_usages: list[AffectedUsage],
    transformation_result: object,
    validation_result: object,
    spec: object,
) -> CompletenessResult:
    """Verify whether every discovered affected usage was handled.

    Classifies each usage based on transformation and validation results,
    detects remaining old API usage, and determines the overall outcome.
    """
    result = CompletenessResult(
        spec_repository=spec.repository,
        spec_technology=spec.technology,
        source_version=spec.source_version,
        target_version=spec.target_version,
        affected_usages=affected_usages,
        transformation_records=getattr(transformation_result, "records", []),
        validation_records=getattr(validation_result, "records", []),
    )

    # Collect evidence for each change
    for usage in affected_usages:
        change = usage.change
        if change.evidence:
            evidence_ref = f"{change.evidence.source}: {change.evidence.section}"
            result.change_evidence.append((change, evidence_ref))

    # Build a map from usage to transformation record
    # Match by file and line since usage objects may be different instances
    usage_to_record: dict[tuple[str, int], TransformationRecord] = {}
    for record in result.transformation_records:
        if hasattr(record.action, "usage") and record.action.usage is not None:
            usage_key = (record.action.usage.file, record.action.usage.line)
            usage_to_record[usage_key] = record

    # Classify each affected usage
    for usage in affected_usages:
        usage_key = (usage.file, usage.line)
        record = usage_to_record.get(usage_key)
        disposition, reason = _classify_usage(usage, record)
        result.usage_dispositions.append((usage, disposition, reason))

        # Update counts
        if disposition == UsageDisposition.MIGRATED:
            result.migrated_count += 1
        elif disposition == UsageDisposition.NOT_MIGRATED:
            result.not_migrated_count += 1
        elif disposition == UsageDisposition.SKIPPED:
            result.skipped_count += 1
        elif disposition == UsageDisposition.FAILED:
            result.failed_count += 1
            result.failures.append(
                (usage, record, reason or "Transformation failed")
            )
        elif disposition == UsageDisposition.MANUAL_REVIEW:
            result.manual_review_count += 1
            result.manual_review_items.append((usage, reason or "Requires manual review"))

    # Detect remaining old API usages from validation
    _detect_remaining_old_usages(result, validation_result)

    # Determine overall outcome
    result.outcome = _determine_outcome(result)

    return result


def _classify_usage(
    usage: AffectedUsage, record: TransformationRecord | None
) -> tuple[UsageDisposition, str]:
    """Classify a single usage based on its transformation record."""
    if record is None:
        # No transformation record means no action was planned/taken
        return UsageDisposition.NOT_MIGRATED, "No corresponding transformation record"

    status = record.status
    strategy = record.strategy

    # Get the string value from enum or use directly if it's a string
    status_str = status.value if hasattr(status, 'value') else str(status)
    strategy_str = strategy.value if hasattr(strategy, 'value') else str(strategy)

    if status_str == "success":
        return UsageDisposition.MIGRATED, "Transformation applied successfully"
    elif status_str == "skipped":
        if strategy_str == "no_transformation":
            return UsageDisposition.SKIPPED, "No transformation required (informational)"
        elif strategy_str == "manual_review":
            return UsageDisposition.MANUAL_REVIEW, "Manual review required"
        else:
            return UsageDisposition.SKIPPED, f"Skipped: {record.error or 'no reason'}"
    elif status_str == "failed":
        return UsageDisposition.FAILED, f"Transformation failed: {record.error or 'unknown error'}"
    elif status_str == "pending":
        return UsageDisposition.NOT_MIGRATED, "Transformation deferred (not yet implemented)"

    return UsageDisposition.NOT_MIGRATED, f"Unknown status: {status}"


def _detect_remaining_old_usages(
    result: CompletenessResult, validation_result: object
) -> None:
    """Detect remaining old API usage from validation records.

    Uses the existing validation results rather than creating a new scanning system.
    """
    validation_records = getattr(validation_result, "records", [])

    for record in validation_records:
        if getattr(record, "check", None) == "residual_old_usage":
            status = getattr(record, "status", None)
            # Handle both enum and string status values
            status_str = status.value if hasattr(status, 'value') else str(status)
            if status_str == "fail":
                result.remaining_old_usages.append(record)


def _determine_outcome(result: CompletenessResult) -> MigrationOutcome:
    """Determine the overall migration outcome based on completeness result."""
    # No migration required if there are no affected usages
    if result.total_affected_usages == 0:
        return MigrationOutcome.NO_MIGRATION_REQUIRED

    # Failed outcome if any transformation failed
    if result.failed_count > 0:
        return MigrationOutcome.FAILED

    # Blocked outcome if there are manual review items
    if result.manual_review_count > 0:
        return MigrationOutcome.BLOCKED

    # Check for remaining old API usages
    has_remaining_old = len(result.remaining_old_usages) > 0

    # Check for not migrated usages
    has_not_migrated = result.not_migrated_count > 0

    # Partically migrated if some remain but not all failed
    if has_remaining_old or has_not_migrated:
        return MigrationOutcome.PARTIALLY_MIGRATED

    # Success if all usages migrated and no remaining old usage
    if result.migrated_count == result.total_affected_usages:
        return MigrationOutcome.SUCCESS

    # Default to partially migrated if we have a mix
    return MigrationOutcome.PARTIALLY_MIGRATED
