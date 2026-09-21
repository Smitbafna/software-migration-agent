"""Public API for the migration agent (Milestone 1)."""

from .discovery import discover_migration, discover_repository, detect_version
from .models import MigrationSpec, VersionEvidence

__all__ = [
    "MigrationSpec",
    "VersionEvidence",
    "discover_migration",
    "discover_repository",
    "detect_version",
]

