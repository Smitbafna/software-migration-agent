"""Core data models for the migration agent (Milestone 1)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class VersionEvidence:
    """Where a declared version was found and what it actually said."""

    source: str          # e.g. "pyproject.toml", "requirements.txt"
    declared: str        # raw declared specifier, e.g. "==1.10.14" or ">=1.10,<2"
    exact: bool          # True only when declared is an exact pin (==/===)
    version: str | None  # concrete version when exact, else None


def _version_key(value: str) -> tuple[int, ...]:
    """Light numeric normalization for comparing versions.

    Intentionally NOT a full semantic-version engine. It handles the common
    "2" vs "2.0.0" equivalence so we don't report a false migration.
    """
    parts = []
    for segment in value.split("."):
        match = re.match(r"\d+", segment)
        parts.append(int(match.group(0)) if match else 0)
    return tuple(parts)


@dataclass
class MigrationSpec:
    """Structured representation of a single migration request."""

    repository: str
    technology: str
    target_version: str
    source_version: str | None = None
    source_version_exact: bool = False
    evidence: list[VersionEvidence] = field(default_factory=list)

    @property
    def migration_required(self) -> bool | None:
        """Whether a migration may be needed.

        Returns None when the source version is unknown (not reliable to
        decide), True when source != target, False when they match.
        """
        if not self.source_version_exact or self.source_version is None:
            return None
        return _version_key(self.source_version) != _version_key(self.target_version)

