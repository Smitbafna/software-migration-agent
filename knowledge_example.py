"""Milestone 2 example: MigrationSpec -> knowledge acquisition -> MigrationChange[].

Includes both a supported migration (pydantic 1.10.14 -> 2) and unsupported
migrations, to show that unknown knowledge is reported explicitly rather than
fabricated.
"""

from pathlib import Path

from migration_agent import MigrationSpec, acquire_migration_knowledge


def show(tag: str, acquisition) -> None:
    print(f"== {tag} ==")
    if not acquisition.supported:
        print(f"  UNSUPPORTED: {acquisition.reason}")
        print()
        return
    print(f"  {len(acquisition.changes)} changes acquired:")
    for change in acquisition.changes:
        print(f"  - [{change.change_type.value}] {change.old} -> {change.new}")
        print(f"      {change.description}")
        print(f"      evidence: {change.evidence.source} | section: {change.evidence.section}")
        print(f"      excerpt : {change.evidence.excerpt!r}")
    print()


def main() -> None:
    # Fits the Milestone 1 spec: exact source pin 1.10.14, target major 2.
    spec = MigrationSpec(
        repository=str(Path("./example_repo")),
        technology="pydantic",
        source_version="1.10.14",
        target_version="2",
    )
    result = acquire_migration_knowledge(spec)
    show(f"SUPPORTED: pydantic {spec.source_version} -> {spec.target_version}", result)

    # No knowledge source registered for this technology yet.
    unknown = MigrationSpec(
        repository=".",
        technology="fastapi",
        source_version="0.110.0",
        target_version="0.115.0",
    )
    show(f"UNSUPPORTED: fastapi {unknown.source_version} -> {unknown.target_version}",
         acquire_migration_knowledge(unknown))

    # Registered technology, but this source/target path is not covered.
    wrong_target = MigrationSpec(
        repository=".",
        technology="pydantic",
        source_version="2.4.0",
        target_version="2.5.0",
    )
    show(f"UNSUPPORTED: pydantic {wrong_target.source_version} -> {wrong_target.target_version}",
         acquire_migration_knowledge(wrong_target))


if __name__ == "__main__":
    main()