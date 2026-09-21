"""Milestone 5 example: execute a MigrationPlan against a working repository copy.

Full Milestone 1 -> 5 pipeline: discover the migration spec, acquire migration
knowledge, discover affected usages, build a migration plan, then execute the
plan against a *working copy* of the repository (the original repo is never
modified).  The result summarises, per action, its strategy, status, whether it
changed anything, and any error.
"""

from pathlib import Path

from migration_agent import (
    acquire_migration_knowledge,
    create_migration_plan,
    discover_affected_usages,
    discover_migration,
    execute_transformation_plan,
)


def main() -> None:
    repo = Path("./example_repo")
    spec = discover_migration(repo, technology="pydantic", target_version="2")

    print(f"Repository: {spec.repository}")
    print(f"Migration required: {spec.migration_required}")
    print()

    knowledge = acquire_migration_knowledge(spec)
    if not knowledge.supported:
        print("Knowledge unsupported:", knowledge.reason)
        return
    print(f"Acquired {len(knowledge.changes)} migration changes.")

    usages = discover_affected_usages(spec, knowledge.changes)
    print(f"Discovered {len(usages)} affected code usages.")

    plan = create_migration_plan(spec, knowledge.changes, usages)
    print(f"Planned {len(plan.actions)} transformation action(s).")
    print()

    result = execute_transformation_plan(plan)
    print(f"Working copy: {result.working_copy}")
    print(f"Overall success: {result.success}")
    print("Records:")
    print("=" * 70)
    for idx, rec in enumerate(result.records, start=1):
        changed = "CHANGED" if rec.changed else "no change"
        marker = "" if rec.error is None else f"  [ERROR: {rec.error}]"
        print(
            f"[{idx}] {rec.file}:{rec.action.usage.line} "
            f"[{rec.strategy.value.upper()}] -> {rec.status.value} "
            f"({changed}){marker}"
        )
    print("=" * 70)
    if result.notes:
        print("Notes:")
        for note in result.notes:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
