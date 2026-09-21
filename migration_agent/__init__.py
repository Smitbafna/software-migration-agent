"""Public API for the migration agent (Milestones 1-4)."""

from .affected_discovery import discover_affected_usages
from .discovery import detect_version, discover_migration, discover_repository
from .knowledge import acquire_migration_knowledge
from .models import (
    AffectedUsage,
    ChangeType,
    Confidence,
    Evidence,
    KnowledgeAcquisition,
    MigrationAction,
    MigrationActionStrategy,
    MigrationChange,
    MigrationPlan,
    MigrationSpec,
    UsageClassification,
    VersionEvidence,
)
from .planning import create_migration_plan, plan_action

__all__ = [
    "AffectedUsage",
    "ChangeType",
    "Confidence",
    "Evidence",
    "KnowledgeAcquisition",
    "MigrationAction",
    "MigrationActionStrategy",
    "MigrationChange",
    "MigrationPlan",
    "MigrationSpec",
    "UsageClassification",
    "VersionEvidence",
    "acquire_migration_knowledge",
    "create_migration_plan",
    "detect_version",
    "discover_affected_usages",
    "discover_migration",
    "discover_repository",
    "plan_action",
]

