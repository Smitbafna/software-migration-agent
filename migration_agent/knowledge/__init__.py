"""Knowledge acquisition (Milestone 2 + Dynamic Knowledge Acquisition).

Pipeline::

    MigrationSpec -> acquire_migration_knowledge() -> KnowledgeAcquisition
                                                        └── list[MigrationChange]

Generic machinery only — nothing here knows about a specific technology.
Technology-specific, evidence-backed change sets live in sibling modules
(e.g. ``pydantic_v2.py``) and are registered via ``register()``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import KnowledgeAcquisition, MigrationChange, MigrationSpec

# Import set_backend from acquisition module for re-export
from .acquisition import set_backend


@dataclass(frozen=True)
class KnowledgeSource:
    """A registered, evidence-backed migration rule set for one version path."""

    technology: str                        # e.g. "pydantic"
    source_major: str                      # e.g. "1"
    target_major: str                      # e.g. "2"
    changes: tuple[MigrationChange, ...]   # the evidence-backed changes


_REGISTRY: dict[tuple[str, str, str], KnowledgeSource] = {}


def register(source: KnowledgeSource) -> None:
    """Register a knowledge source; one (technology, source, target) path each."""
    key = (source.technology, source.source_major, source.target_major)
    if key in _REGISTRY:
        raise ValueError(f"Duplicate knowledge source for path {key!r}")
    _REGISTRY[key] = source


def _major_of(version: str | None) -> str | None:
    """First numeric component of a version, e.g. '1.10.14' -> '1'."""
    if version is None:
        return None
    match = re.match(r"\d+", version.strip())
    return match.group(0) if match else None


def acquire_migration_knowledge(spec: MigrationSpec) -> KnowledgeAcquisition:
    """Acquire structured migration knowledge for ``spec``.

    Knowledge is returned only when a registered source covers the requested
    (technology, source major, target major) path. Any other case returns an
    explicit ``unsupported`` result with a reason — never fabricated changes.

    This function first checks for static registered knowledge, then attempts
    dynamic acquisition from authoritative web sources for unknown paths.
    """
    technology = spec.technology.strip().lower()
    source_major = _major_of(spec.source_version)
    target_major = _major_of(spec.target_version)

    if not technology:
        return _unsupported(spec, "No technology was specified in the migration spec.")
    if target_major is None:
        return _unsupported(
            spec,
            f"Unrecognized target version {spec.target_version!r}; "
            "cannot select a knowledge source.",
        )

    source = _REGISTRY.get((technology, source_major, target_major))
    if source is not None:
        return KnowledgeAcquisition(spec=spec, supported=True, changes=list(source.changes))

    # No static knowledge — attempt dynamic acquisition from web.
    return _acquire_from_web(spec, technology, source_major, target_major)


def _unavailable_reason(technology: str, spec: MigrationSpec, source_major: str | None, target_major: str) -> str:
    """Explain why no source matched, distinguishing the common cases."""
    known = sorted({key[0] for key in _REGISTRY})
    if technology not in known:
        return (
            f"No knowledge source is registered for technology {spec.technology!r} "
            f"(registered: {', '.join(known) or 'none'})."
        )
    if source_major is None:
        return (
            f"The {technology} source version is unknown (no concrete version in the spec), "
            f"so it cannot be confirmed which {technology} migration knowledge applies."
        )
    return (
        f"No registered knowledge source covers {technology} {source_major}.x -> "
        f"{target_major}.x for spec (source {spec.source_version!r}, target {spec.target_version!r})."
    )


def _unsupported(spec: MigrationSpec, reason: str) -> KnowledgeAcquisition:
    return KnowledgeAcquisition(spec=spec, supported=False, reason=reason)


# ---------------------------------------------------------------------------
# Dynamic knowledge acquisition from web sources
# ---------------------------------------------------------------------------


def _acquire_from_web(spec: MigrationSpec, technology: str, source_major: str | None, target_major: str) -> KnowledgeAcquisition:
    """Attempt to acquire migration knowledge from the web.

    Searches for authoritative migration documentation, retrieves and inspects
    source pages, and extracts MigrationChange objects with evidence.

    If no authoritative migration information can be found or verified,
    returns an unsupported result with an explicit reason.
    """
    from .acquisition import acquire_migration_knowledge as dynamic_acquire, set_backend
    return dynamic_acquire(spec)


# Register the initial evidence-backed knowledge source (Pydantic 1.x -> 2.x).
from . import pydantic_v2 as _pydantic_v2  # noqa: E402,F401

register(
    KnowledgeSource(
        technology=_pydantic_v2.TECHNOLOGY,
        source_major=_pydantic_v2.SOURCE_MAJOR,
        target_major=_pydantic_v2.TARGET_MAJOR,
        changes=tuple(_pydantic_v2.changes()),
    ),
)

__all__ = [
    "KnowledgeAcquisition",
    "KnowledgeSource",
    "MigrationChange",
    "acquire_migration_knowledge",
    "register",
    "set_backend",
]
