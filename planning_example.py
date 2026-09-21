"""Milestone 4 example: MigrationSpec + MigrationChange[] + AffectedUsage[] -> MigrationPlan.

Demonstrates the full Milestone 4 pipeline: starting from a repository,
discover its migration spec, acquire migration knowledge (changes),
discover affected usages, then build a migration plan with transformation
actions.  No repository files are modified.
"""

from pathlib import Path

from migration_agent import (
    MigrationSpec,
    acquire_migration_knowledge,
    create_migration_plan,
    discover_affected_usages,
    discover_migration,
)


def main() -> None:
    repo = Path("./example_repo")
    spec = discover_migration(repo, technology="pydantic", target_version="2")

    print(f"Repository: {spec.repository}")
    if spec.source_version:
        print(f"Source version: {spec.source_version}")
    print(f"Target version: {spec.target_version}")
    if spec.migration_required:
        print("Migration: REQUIRED")
    elif spec.migration_required is False:
        print("Migration: NOT REQUIRED")
    else:
        print("Migration: UNKNOWN (source version not an exact pin)")
    print()

    knowledge = acquire_migration_knowledge(spec)
    if not knowledge.supported:
        print("Knowledge unsupported:", knowledge.reason)
        return

    print(f"Acquired {len(knowledge.changes)} migration changes.")
    usages = discover_affected_usages(spec, knowledge.changes)
    print(f"Discovered {len(usages)} affected code usages.")
    print()

    plan = create_migration_plan(spec, knowledge.changes, usages)

    print(f"Migration plan: {len(plan.actions)} action(s) planned.")
    print("=" * 60)
    for idx, action in enumerate(plan.actions, start=1):
        print(f"[{idx}] {action.usage.file}:{action.usage.line} "
              f"[{action.strategy.value.upper()}]")
        print(f"    Change: {action.old} -> {action.new}")
        print(f"    Reason: {action.reason}")
        print()

    if plan.notes:
        print("Notes:")
        for note in plan.notes:
            print(f"  - {note}")
    else:
        print("No notes.")


if __name__ == "__main__":
    main()
