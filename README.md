# Migration Agent (experimental alpha)

> **This is an experimental alpha release (`0.1.0a1`).** It is a research
> prototype for exploring evidence-backed dependency migration assistance. It
> does **not** perform fully autonomous migration of arbitrary repositories.

## What it is

Migration Agent analyses a Python repository and assists with upgrading a
pinned dependency from one major version to another. It walks a fixed,
auditable pipeline:

```
MigrationSpec (discovery)
  → Migration Knowledge (static registry + dynamic web acquisition)
  → Affected-Code Discovery (AST-assisted usage search)
  → Planning (one action per usage, with an explicit strategy)
  → Transformation (mechanical edits in a working copy; original untouched)
  → Validation (syntax, residual old-usage, target-usage, test suite)
  → Completeness (every usage gets a disposition)
  → Report (evidence-preserving MigrationReport)
```

The package's only runtime requirement is the Python standard library.

## Problem it addresses

Major-version upgrades (e.g. Pydantic 1.x → 2.x) rename, remove, or subtly
change APIs. Doing such an upgrade by hand means: reading the migration
guide, finding every affected call site, editing each one, and verifying
nothing was missed. Migration Agent mechanises that loop while keeping every
claim traceable to cited documentation.

## Key ideas

- **Dynamic migration knowledge acquisition.** For version paths without a
  built-in rule set, the agent searches the web for official migration
  documentation (preferring authoritative sources), fetches the pages, and
  extracts `MigrationChange` objects from the page bodies. Search snippets
  are never used as evidence.
- **Evidence-backed migration changes.** Every `MigrationChange` carries an
  `Evidence` record (document, section, verbatim excerpt, URL), preserved all
  the way through to the final `MigrationReport`.
- **Safety behaviour.** The original repository is never modified; edits
  happen in a working copy. Unknown versions produce an explicit
  `unsupported` result instead of fabricated knowledge. Ambiguous usages are
  planned as `LLM_ASSISTED` and left pending rather than guessed at.
- **Completeness accounting.** Every discovered usage receives a disposition
  (`MIGRATED`, `NOT_MIGRATED`, `SKIPPED`, `FAILED`, `MANUAL_REVIEW`) and the
  overall outcome (`SUCCESS`, `PARTIALLY_MIGRATED`, `BLOCKED`, `FAILED`,
  `NO_MIGRATION_REQUIRED`) is derived from those dispositions.

## Capabilities (current)

- Repository discovery: finds `pyproject.toml`, `requirements.txt`,
  `requirements/*.txt`, `setup.py`, `setup.cfg` dependency metadata.
- Version evidence: exact pins (`==`) determine the source version;
  non-exact constraints are reported as "unknown" rather than guessed.
- Static evidence-backed knowledge for **Pydantic 1.x → 2.x** (a
  representative subset of the official migration guide).
- Dynamic web knowledge for other technology/version paths via a
  standard-library search/fetch backend (injectable for tests via
  `set_backend()`).
- AST-assisted affected-usage discovery, per-usage planning, mechanical
  transformation of exact matches, syntax/residual/target/test validation,
  completeness verification, and report generation.

## Current limitations (read before using)

- **Knowledge-source verification still needs strengthening.** The dynamic
  backend can accept documentation from a different project with a similar
  name when it ranks highly (observed: Django REST Framework release notes
  returned for a Django query). Cross-project results must be checked.
- **Some transformations are deferred as `LLM_ASSISTED`.** Text-only
  (non-AST-confirmed) usages are deliberately left pending; the executor
  does not guess. Behaviour-only changes without exact code patterns are not
  discovered as usages.
- **Documented M3/M8 end-to-end limitations:** multi-file migrations may be
  partial; text matches inside strings/docstrings can be flagged as
  candidate usages; exact-match transformation can fail on conflicting
  patterns (see `E2E_TEST_SUMMARY.md` in the source repository).
- **Behavioural migration changes may require additional
  knowledge/extraction support** beyond the current exact-pattern machinery.

## Installation

```bash
pip install migration-agent
```

Requires Python 3.12 or newer. There are no runtime dependencies.

## Minimal usage

The package exposes a library API (there is no command-line interface):

```python
from pathlib import Path
from migration_agent import (
    acquire_migration_knowledge,
    create_migration_plan,
    discover_affected_usages,
    discover_migration,
    execute_transformation_plan,
    execute_validation,
    generate_report,
    verify_completeness,
)

repo = Path("./my-repo")
spec = discover_migration(repo, technology="pydantic", target_version="2")
print("source:", spec.source_version, "target:", spec.target_version)

knowledge = acquire_migration_knowledge(spec)
print("supported:", knowledge.supported)
if not knowledge.supported:
    print("reason:", knowledge.reason)
else:
    usages = discover_affected_usages(repo, knowledge.changes)
    plan = create_migration_plan(spec, knowledge.changes, usages)
    result = execute_transformation_plan(repo, plan)
    validation = execute_validation(result.working_copy, usages, knowledge.changes)
    completeness = verify_completeness(spec, usages, plan, result, validation)
    report = generate_report(completeness)
    print("outcome:", report.outcome)
```

For a fully worked offline example using a deterministic injected backend,
see `examples/dynamic_knowledge_demo.py --mock` in the source repository.
