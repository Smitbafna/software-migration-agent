"""Milestone 1 example: point the agent at a Python repo and get a MigrationSpec."""

from pathlib import Path

from migration_agent import discover_migration, discover_repository


def main() -> None:
    repository = Path("./example_repo")
    technology = "pydantic"
    target_version = "2"

    info = discover_repository(repository)
    print(f"Repository: {info.repository}")
    print("Dependency metadata found:")
    for f in info.dependency_files:
        print(f"  - {f}")
    if not info.found:
        print("  (none — no Python dependency metadata detected)")
        return

    print()
    spec = discover_migration(repository, technology, target_version)
    print(spec)
    print()
    print("Evidence:")
    for ev in spec.evidence:
        state = "exact pin" if ev.exact else "constraint (non-exact)"
        print(f"  - {ev.source}: declared={ev.declared!r} [{state}]")
    print()
    if spec.migration_required is None:
        print(
            "Migration status: UNKNOWN — the declared source version is not an "
            "exact pin, so we will not guess an installed version."
        )
    elif spec.migration_required:
        print("Migration status: REQUIRED (source_version != target_version)")
    else:
        print("Migration status: NOT REQUIRED (source_version == target_version)")


if __name__ == "__main__":
    main()

