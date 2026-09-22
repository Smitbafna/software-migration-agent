"""Public API for the migration agent (Milestones 1-8)."""

from .affected_discovery import discover_affected_usages
from .completeness import (
    CompletenessResult,
    MigrationOutcome,
    UsageDisposition,
    verify_completeness,
)
from .discovery import detect_version, discover_migration, discover_repository
from .knowledge import acquire_migration_knowledge, set_backend
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
    ValidationRecord,
    ValidationResult,
    ValidationStatus,
    VersionEvidence,
)
from .planning import create_migration_plan, plan_action
from .report import MigrationReport, generate_report
from .transformation import (
    TransformationEngine,
    execute_transformation_plan,
)
from .validation import (
    ValidationEngine,
    execute_validation,
)

__version__ = "0.1.0a1"

__all__ = [
    "__version__",
    "AffectedUsage",
    "ChangeType",
    "CompletenessResult",
    "Confidence",
    "Evidence",
    "KnowledgeAcquisition",
    "MigrationAction",
    "MigrationActionStrategy",
    "MigrationChange",
    "MigrationPlan",
    "MigrationReport",
    "MigrationSpec",
    "MigrationOutcome",
    "TransformationEngine",
    "TransformationRecord",
    "TransformationResult",
    "TransformationStatus",
    "UsageClassification",
    "UsageDisposition",
    "ValidationEngine",
    "ValidationRecord",
    "ValidationResult",
    "ValidationStatus",
    "acquire_migration_knowledge",
    "create_migration_plan",
    "detect_version",
    "discover_affected_usages",
    "discover_migration",
    "discover_repository",
    "execute_transformation_plan",
    "execute_validation",
    "generate_report",
    "plan_action",
    "set_backend",
    "verify_completeness",
]
