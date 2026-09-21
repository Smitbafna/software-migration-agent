"""Deterministic repository discovery for Python projects (Milestone 1)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .models import MigrationSpec, VersionEvidence

# Requirement specifier that denotes an exact pin. We only treat a bare
# ==/=== followed by a concrete version as "exact"; anything else (ranges,
# ~=, >=, wildcards, ...) is a constraint and gives no reliable version.
_EXACT_RE = re.compile(r"^(?:==|===)\s*([^,;*]+?)\s*$")
# Name[extras] then the remaining specifier text.
_REQ_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(.*)$")


@dataclass
class RepositoryInfo:
    """Structured summary of what dependency metadata a repo exposes."""

    repository: Path
    dependency_files: list[Path] = field(default_factory=list)
    found: bool = False


def discover_repository(repository: str | Path) -> RepositoryInfo:
    """Locate dependency metadata files in a Python repository.

    Supports pyproject.toml, requirements.txt, and requirements/*.txt.
    """
    root = Path(repository)
    candidates = [root / "pyproject.toml", root / "requirements.txt"]
    req_dir = root / "requirements"
    if req_dir.is_dir():
        candidates.extend(sorted(req_dir.glob("*.txt")))

    files = [p for p in candidates if p.is_file()]
    return RepositoryInfo(repository=root, dependency_files=files, found=bool(files))


def _parse_requirement(text: str) -> tuple[str, str] | None:
    """Return (normalized_package_name, specifier) for a requirement line."""
    text = text.strip()
    if not text or text.startswith(("#", "-", "git+", "svn+", "hg+", "http", "file:", "ssh:")):
        return None
    # Drop environment markers (the part after ';').
    text = text.split(";", 1)[0].strip()
    match = _REQ_RE.match(text)
    if not match:
        return None
    name = match.group(1).lower()
    specifier = match.group(2).strip()
    return name, specifier


def _exact_version(specifier: str) -> str | None:
    """Return the concrete version if the specifier is an exact pin, else None."""
    match = _EXACT_RE.match(specifier)
    if not match:
        return None
    version = match.group(1).strip()
    if "*" in version:  # e.g. ==1.10.* is a prefix, not a pin
        return None
    return version


def _evidence_from_file(path: Path, technology: str) -> list[VersionEvidence]:
    """Return VersionEvidence for `technology` found in a single file."""
    tech = technology.lower()
    results: list[VersionEvidence] = []

    if path.name == "pyproject.toml":
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
            return results
        tables = []
        project = data.get("project", {})
        tables.extend(project.get("dependencies", []))
        tables.extend(v for opt in project.get("optional-dependencies", {}).values() for v in opt)
        poetry = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        for entry in tables:
            if isinstance(entry, str):
                parsed = _parse_requirement(entry)
                if parsed and parsed[0] == tech:
                    results.append(_mk_evidence(path.name, parsed[1]))
            # Poetry-style: { "pydantic": ">=1.10,<2" } or { "pydantic": {version=...} }
        for name, value in poetry.items():
            if name.lower() == tech:
                if isinstance(value, str):
                    results.append(_mk_evidence(path.name, value))
                elif isinstance(value, dict) and "version" in value:
                    results.append(_mk_evidence(path.name, str(value["version"])))
        return results

    # Plain text requirement files.
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    for line in lines:
        parsed = _parse_requirement(line)
        if parsed and parsed[0] == tech:
            results.append(_mk_evidence(path.name, parsed[1]))
    return results


def _mk_evidence(source: str, specifier: str) -> VersionEvidence:
    exact = _exact_version(specifier)
    return VersionEvidence(
        source=source,
        declared=specifier or "(no version declared)",
        exact=exact is not None,
        version=exact,
    )


# Priority order: pyproject.toml beats requirements.txt beats requirements/*.txt.
_PRIORITY = {"pyproject.toml": 0, "requirements.txt": 1}


def detect_version(repository: str | Path, technology: str) -> list[VersionEvidence]:
    """Collect all version evidence for `technology` across the repository."""
    info = discover_repository(repository)
    evidence: list[VersionEvidence] = []
    for path in sorted(info.dependency_files, key=lambda p: _PRIORITY.get(p.name, 2)):
        evidence.extend(_evidence_from_file(path, technology))
    return evidence


def discover_migration(
    repository: str | Path, technology: str, target_version: str
) -> MigrationSpec:
    """Full Milestone 1 pipeline: discovery -> tech id -> version -> spec."""
    evidence = detect_version(repository, technology)

    # Prefer the first exact pin; otherwise the source version is unknown.
    source_version = None
    source_exact = False
    for ev in evidence:
        if ev.exact:
            source_version = ev.version
            source_exact = True
            break

    return MigrationSpec(
        repository=str(Path(repository)),
        technology=technology,
        target_version=target_version,
        source_version=source_version,
        source_version_exact=source_exact,
        evidence=evidence,
    )

