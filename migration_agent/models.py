"""Core data models for the migration agent (Milestones 1 + 2)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


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


class ChangeType(Enum):
    """High-level category of a single migration change (technology-agnostic)."""

    REPLACEMENT = "replacement"      # old API/callable/name replaced by a new one
    REMOVAL = "removal"              # old API removed with no direct replacement
    DEPRECATION = "deprecation"      # old API deprecated in favor of a new one
    CONFIGURATION = "configuration"  # settings / config key or value changed
    SIGNATURE = "signature"          # arguments / calling convention changed
    BEHAVIOR = "behavior"            # same API, different observable behavior


class Confidence(Enum):
    """How strongly a change is backed by its evidence."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class Evidence:
    """Authoritative documentation reference backing a MigrationChange.

    ``excerpt`` must be a short verbatim quote retrievable from the cited
    document, so that every claim in a migration change can be checked.
    Nothing in ``Evidence`` is synthesized by a model.
    """

    source: str            # document title, e.g. "Pydantic Migration Guide (V1 -> V2)"
    section: str           # section/heading within the document
    excerpt: str           # short verbatim quote supporting the change
    url: str | None = None # location of the document, when known


@dataclass(frozen=True)
class MigrationChange:
    """One technology-agnostic migration change, backed by mandatory evidence."""

    change_type: ChangeType    # category of change
    description: str           # what changes and what to do about it
    evidence: Evidence         # mandatory: why the agent believes this exists
    old: str | None = None     # old API / setting / behavior (when applicable)
    new: str | None = None     # new API / setting / behavior (when applicable)
    confidence: Confidence = Confidence.HIGH


@dataclass
class KnowledgeAcquisition:
    """Result of knowledge acquisition for a MigrationSpec.

    ``supported`` is False (with a ``reason``) whenever no registered evidence
    source covers the requested migration; the system never fabricates
    changes for an unsupported migration.
    """

    spec: MigrationSpec
    supported: bool
    changes: list[MigrationChange] = field(default_factory=list)
    reason: str | None = None  # why knowledge is unavailable (when supported=False)

