"""Focused tests for Milestone 6 — Validation & Migration Verification.

Tests cover the four validation checks:

* syntax success / syntax failure
* residual old usage detection
* test command success / test command failure / no tests
* repository with no tests (SKIPPED)

All checks execute against a *working copy* and never modify repository files.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from migration_agent import (
    AffectedUsage,
    ChangeType,
    Confidence,
    Evidence,
    MigrationAction,
    MigrationActionStrategy,
    MigrationChange,
    MigrationPlan,
    MigrationSpec,
    TransformationStatus,
    UsageClassification,
    execute_transformation_plan,
    execute_validation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _evidence():
    return Evidence(
        source="Pydantic Migration Guide (V1 -> V2)",
        section="Changes to pydantic.BaseModel",
        excerpt="parse_obj() model_validate()",
        url="https://docs.pydantic.dev/2.10/migration/",
    )


def _make_change(change_type, old, new):
    return MigrationChange(
        change_type=change_type,
        old=old,
        new=new,
        description="test change",
        evidence=_evidence(),
        confidence=Confidence.HIGH,
    )


def _make_usage(change, file="app.py", line=1, classification=UsageClassification.CONFIRMED):
    return AffectedUsage(
        change=change,
        file=file,
        line=line,
        source_context="ctx",
        classification=classification,
    )


def _make_plan(repo, actions):
    spec = MigrationSpec(
        repository=str(repo),
        technology="pydantic",
        source_version="1.10.14",
        target_version="2",
        source_version_exact=True,
    )
    return MigrationPlan(spec=spec, actions=actions)


def _make_action(file, line, strategy, old, new):
    change = _make_change(ChangeType.REPLACEMENT, old, new)
    usage = _make_usage(change, file=file, line=line)
    return MigrationAction(
        usage=usage,
        strategy=strategy,
        reason="test reason",
        old=old,
        new=new,
    )


@pytest.fixture
def repo(tmp_path):
    """A tiny repository with a single Python source file."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class User(BaseModel):\n"
        "    @validator(\"name\")\n"
        "    def name_field(cls, v, field, config):\n"
        "        return v\n\n"
        "def main():\n"
        "    user = User.parse_obj(data)\n"
        "    return user.dict()\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture
def transformed_wc(tmp_path, repo):
    """Execute the plan against a working copy and return the working-copy path."""
    plan = _make_plan(
        repo,
        [
            _make_action(
                "app.py", 8, MigrationActionStrategy.TEXT_EDIT,
                "User.parse_obj(data)", "User.model_validate(data)",
            ),
        ],
    )
    result = execute_transformation_plan(plan)
    assert result.success
    return Path(result.working_copy)


# ---------------------------------------------------------------------------
# 1. Syntax validation: success
# ---------------------------------------------------------------------------


def test_syntax_success(transformed_wc):
    result = execute_validation(transformed_wc)
    syntax = next(r for r in result.records if r.check == "syntax")
    assert syntax.status.name == "PASS"
    assert syntax.command is not None
    assert "py_compile" in syntax.command
    assert syntax.affected_files
    assert any(f.endswith("app.py") for f in syntax.affected_files)


# ---------------------------------------------------------------------------
# 2. Syntax validation: failure (broken file injected)
# ---------------------------------------------------------------------------


def test_syntax_failure(tmp_path, repo):
    wc = tmp_path / "wc"
    shutil.copytree(repo, wc)
    (wc / "broken.py").write_text("def broken(\n", encoding="utf-8")

    result = execute_validation(wc)
    syntax = next(r for r in result.records if r.check == "syntax")
    assert syntax.status.name == "FAIL"
    assert syntax.error is not None or syntax.output
    assert "broken.py" in syntax.output or "broken.py" in syntax.affected_files


# ---------------------------------------------------------------------------
# 3. Residual old usage detection (found)
# ---------------------------------------------------------------------------


def test_residual_old_usage_detected(tmp_path, repo):
    wc = tmp_path / "wc"
    shutil.copytree(repo, wc)
    (wc / "app.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class User(BaseModel):\n"
        "    @validator(\"name\")\n"
        "    def name_field(cls, v, field, config):\n"
        "        return v\n\n"
        "def main():\n"
        "    user = User.parse_obj(data)\n"
        "    return user.model_dump()\n",
        encoding="utf-8",
    )

    change = _make_change(ChangeType.REPLACEMENT, "User.parse_obj(data)", "User.model_validate(data)")
    usage = _make_usage(change, file="app.py", line=8)
    result = execute_validation(wc, usages=[usage], changes=[change])

    residual = next(r for r in result.records if r.check == "residual_old_usage")
    assert residual.status.name == "FAIL"
    assert "app.py" in residual.affected_files


# ---------------------------------------------------------------------------
# 4. Residual old usage: none found (clean)
# ---------------------------------------------------------------------------


def test_residual_old_usage_clean(transformed_wc):
    change = _make_change(ChangeType.REPLACEMENT, "User.parse_obj(data)", "User.model_validate(data)")
    usage = _make_usage(change, file="app.py", line=8)
    result = execute_validation(transformed_wc, usages=[usage], changes=[change])

    residual = next(r for r in result.records if r.check == "residual_old_usage")
    assert residual.status.name == "PASS"
    assert "No residual old usages" in residual.output


# ---------------------------------------------------------------------------
# 5. Test command success (repo with pytest in pyproject.toml)
# ---------------------------------------------------------------------------


def test_test_command_success(tmp_path):
    """A repo with pyproject.toml declaring pytest should run pytest and pass."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname = \"demo\"\nversion = \"0.1.0\"\n"
        "[tool.pytest]\nminversion = \"7.0\"\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    tests_dir = root / "tests"
    tests_dir.mkdir()
    # Self-contained test — no imports needed so it works in any cwd.
    (tests_dir / "test_app.py").write_text(
        "def test_add(): assert 1 + 2 == 3\n",
        encoding="utf-8",
    )

    result = execute_validation(root)
    test_rec = next(r for r in result.records if r.check == "test_suite")
    assert test_rec.status.name == "PASS"


# ---------------------------------------------------------------------------
# 6. Test command failure (failing test)
# ---------------------------------------------------------------------------


def test_test_command_failure(tmp_path):
    """A repo with a failing test should produce a FAIL record."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text(
        "[project]\nname = \"demo\"\nversion = \"0.1.0\"\n"
        "[tool.pytest]\nminversion = \"7.0\"\n",
        encoding="utf-8",
    )
    (root / "app.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "def test_add(): assert False\n",
        encoding="utf-8",
    )

    result = execute_validation(root)
    test_rec = next(r for r in result.records if r.check == "test_suite")
    assert test_rec.status.name == "FAIL"
    assert test_rec.error is not None or test_rec.output


# ---------------------------------------------------------------------------
# 7. Repository with no tests -> SKIPPED
# ---------------------------------------------------------------------------


def test_no_tests_skip(transformed_wc):
    """A transformed working copy with no test infrastructure is SKIPPED."""
    result = execute_validation(transformed_wc)
    test_rec = next(r for r in result.records if r.check == "test_suite")
    assert test_rec.status.name == "SKIPPED"


# ---------------------------------------------------------------------------
# 8. Validation does not modify repository files
# ---------------------------------------------------------------------------


def test_validation_readonly(tmp_path, repo):
    """Execute validation against the original repository path; it must not be modified."""
    app_original = (repo / "app.py").read_bytes()
    result = execute_validation(repo)
    assert (repo / "app.py").read_bytes() == app_original
    assert any(r.check == "syntax" for r in result.records)


# ---------------------------------------------------------------------------
# 9. ValidationResult.success is False when a check fails
# ---------------------------------------------------------------------------


def test_validation_result_success_flag(tmp_path, repo):
    wc = tmp_path / "wc"
    shutil.copytree(repo, wc)
    (wc / "broken.py").write_text("def broken(\n", encoding="utf-8")

    result = execute_validation(wc)
    assert result.success is False
    assert any(r.status.name == "FAIL" for r in result.records)


# ---------------------------------------------------------------------------
# 10. End-to-end: transform then validate the example repo
# ---------------------------------------------------------------------------


def test_end_to_end_validate_example_repo(tmp_path):
    """Full Milestone 1->6 wiring: original repo untouched, validation produces records."""
    repo = Path(__file__).resolve().parents[1] / "example_repo"
    app_original = (repo / "app.py").read_bytes()

    from migration_agent import (
        acquire_migration_knowledge,
        create_migration_plan,
        discover_affected_usages,
        discover_migration,
    )

    spec = discover_migration(repo, technology="pydantic", target_version="2")
    knowledge = acquire_migration_knowledge(spec)
    assert knowledge.supported, knowledge.reason
    usages = discover_affected_usages(spec, knowledge.changes)
    plan = create_migration_plan(spec, knowledge.changes, usages)

    # Transform.
    transform_result = execute_transformation_plan(plan)
    assert transform_result.success or any(
        r.status == TransformationStatus.PENDING for r in transform_result.records
    )

    wc = Path(transform_result.working_copy)

    # Validate.
    result = execute_validation(wc, usages=usages, changes=knowledge.changes)

    # The original repository must be byte-for-byte unchanged.
    assert (repo / "app.py").read_bytes() == app_original

    # Validation must have run at least syntax + residual + target + test_suite checks.
    checks = {r.check for r in result.records}
    assert "syntax" in checks
    assert "residual_old_usage" in checks
    assert "target_usage" in checks
    assert "test_suite" in checks

    # Syntax must pass on the transformed working copy.
    syntax = next(r for r in result.records if r.check == "syntax")
    assert syntax.status.name == "PASS"
