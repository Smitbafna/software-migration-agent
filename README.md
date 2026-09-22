# Migration Agent — experimental alpha

> **Alpha (`0.1.0a1`).** Research prototype for evidence-backed dependency-migration assistance. It does **not** autonomously migrate arbitrary repositories.

Migration Agent helps upgrade a pinned Python dependency across a major version. It discovers the pinned source version, finds affected call sites, plans and applies mechanical edits in a working copy, validates the result, and reports every usage disposition with cited documentation.

## Install

```bash
pip install migration-agent
```

Requires Python 3.12+. Runtime dependencies: none; the package uses only the standard library.

## How it works

Fixed, auditable pipeline — discovery → knowledge → affected-code search →
planning → transformation → validation → completeness → report:

- **Dynamic knowledge acquisition.** For version paths without built-in rules,
  the agent searches for official migration docs (preferring authoritative
  sources), fetches the pages, and extracts `MigrationChange` objects from
  page bodies — never from search snippets.
- **Evidence-backed changes.** Every change carries document, section,
  verbatim excerpt, and URL, preserved through to the final report.
- **Safe by default.** The original repo is never modified (edits happen in a
  working copy); unknown versions yield an explicit `unsupported` result;
  ambiguous usages are planned as `LLM_ASSISTED` and left pending.
- **Complete accounting.** Every usage gets a disposition (`MIGRATED`,
  `NOT_MIGRATED`, `SKIPPED`, `FAILED`, `MANUAL_REVIEW`); the outcome
  (`SUCCESS`, `PARTIALLY_MIGRATED`, `BLOCKED`, `FAILED`,
  `NO_MIGRATION_REQUIRED`) is derived from them.

Built-in knowledge covers **Pydantic 1.x → 2.x**; other paths use the web
backend (injectable via `set_backend()` for tests).

## Example

Library API — there is no CLI. Full pipeline in one snippet:

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

knowledge = acquire_migration_knowledge(spec)
if not knowledge.supported:
    print("reason:", knowledge.reason)
else:
    usages = discover_affected_usages(repo, knowledge.changes)
    plan = create_migration_plan(spec, knowledge.changes, usages)
    result = execute_transformation_plan(plan)
    validation = execute_validation(result.working_copy, usages, knowledge.changes)
    completeness = verify_completeness(usages, result, validation, spec)
    report = generate_report(completeness)
    print("outcome:", report.outcome)
```

## Limitations

- Knowledge-source verification needs strengthening: the web backend can
  accept a similarly named project's docs (observed: Django REST Framework
  notes for a Django query) — check evidence URLs.
- Text-only usages are planned as `LLM_ASSISTED` and left pending; the
  executor never guesses. Behaviour-only changes without code patterns are
  not discovered.
- Multi-file migrations may be partial; string/docstring text matches can
  be flagged as candidates; exact-match transformation can fail on
  conflicting patterns.
