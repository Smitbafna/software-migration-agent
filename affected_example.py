"""Milestone 3 example: MigrationSpec + MigrationChange[] -> AffectedUsage[].

Analyzes the example repository for usages affected by Pydantic V1 -> V2 changes.
"""

from pathlib import Path

from migration_agent import (
    MigrationSpec,
    acquire_migration_knowledge,
    discover_affected_usages,
)


def main() -> None:
    repo = Path("./example_repo")
    spec = MigrationSpec(
        repository=str(repo),
        technology="pydantic",
        source_version="1.10.14",
        target_version="2",
    )

    print(f"Analyzing repository: {spec.repository}")
    knowledge = acquire_migration_knowledge(spec)
    if not knowledge.supported:
        print("Knowledge unsupported:", knowledge.reason)
        return

    print(f"Acquired {len(knowledge.changes)} migration changes.")
    print()

    usages = discover_affected_usages(spec, knowledge.changes)
    print(f"Discovered {len(usages)} affected code usages:")
    print("=" * 60)

    for idx, usage in enumerate(usages, start=1):
        print(f"[{idx}] {usage.file}:{usage.line} [{usage.classification.value.upper()}]")
        print(f"    Change: {usage.change.old} -> {usage.change.new}")
        print("    Source context:")
        for line in usage.source_context.splitlines():
            print(f"      {line}")
        print()


if __name__ == "__main__":
    main()
