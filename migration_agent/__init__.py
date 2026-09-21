"""Public API for the migration agent (Milestones 1 + 2)."""

from .discovery import discover_migration, discover_repository, detect_version
from .knowledge import acquire_migration_knowledge
from .models import (
    ChangeType,
    Confidence,
    Evidence,
    KnowledgeAcquisition,
    MigrationChange,
    MigrationSpec,
    VersionEvidence,
)

__all__ = [
    "ChangeType",
    "Confidence",
    "Evidence",
    "KnowledgeAcquisition",
    "MigrationChange",
    "MigrationSpec",
    "VersionEvidence",
    "acquire_migration_knowledge",
    "detect_version",
    "discover_migration",
    "discover_repository",
]

