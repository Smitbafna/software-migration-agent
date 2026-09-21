"""Public API for the migration agent (Milestones 1-5)."""

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
    TransformationRecord,
    TransformationResult,
    TransformationStatus,
    UsageClassification,
    VersionEvidence,
)
from .planning import create_migration_plan, plan_action
from .transformation import (
    TransformationEngine,
    execute_transformation_plan,
)

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
    "TransformationEngine",
    "TransformationRecord",
    "TransformationResult",
    "TransformationStatus",
    "UsageClassification",
    "VersionEvidence",
    "acquire_migration_knowledge",
    "create_migration_plan",
    "detect_version",
    "discover_affected_usages",
    "discover_migration",
    "discover_repository",
    "execute_transformation_plan",
    "plan_action",
]
