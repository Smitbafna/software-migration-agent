"""Focused tests for Milestone 5 — Transformation Execution."""

from __future__ import annotations

import ast
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
    TransformationRecord,
    TransformationResult,
    TransformationStatus,
    UsageClassification,
    execute_transformation_plan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _evidence() -> Evidence:
    return Evidence(
        source="Pydantic Migration Guide (V1 -> V2)",
        section="Changes to pydantic.BaseModel",
        excerpt="parse_obj() model_validate()",
        url="https://docs.pydantic.dev/2.10/migration/",
    )


def _make_change(
    change_type: ChangeType,
    old: str | None,
    new: str | None,
) -> MigrationChange:
    return MigrationChange(
        change_type=change_type,
        old=old,
        new=new,
        description="test change",
        evidence=_evidence(),
        confidence=Confidence.HIGH,
    )


def _make_action(
    file: str,
    line: int,
    strategy: MigrationActionStrategy,
    old: str | None,
    new: str | None,
    change_type: ChangeType = ChangeType.REPLACEMENT,
    classification: UsageClassification = UsageClassification.CONFIRMED,
) -> MigrationAction:
    change = _make_change(change_type, old, new)
    usage = AffectedUsage(
        change=change,
        file=file,
        line=line,
        source_context="ctx",
        classification=classification,
    )
    return MigrationAction(
        usage=usage,
        strategy=strategy,
        reason="test reason",
        old=old,
        new=new,
    )


def _make_plan(repo: Path, actions: list[MigrationAction]) -> MigrationPlan:
    spec = MigrationSpec(
        repository=str(repo),
        technology="pydantic",
        source_version="1.10.14",
        target_version="2",
        source_version_exact=True,
    )
    # Force actions regardless of discovery/planning.
    return MigrationPlan(spec=spec, actions=actions)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
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


# ---------------------------------------------------------------------------
# 1. Successful deterministic (TEXT_EDIT) edit
# ---------------------------------------------------------------------------

def test_successful_deterministic_edit(repo: Path) -> None:
    """TEXT_EDIT applies a targeted, deterministic text replacement."""
    # "user.dict()" appears on line 8 -> nearest to discovered line 8.
    plan = _make_plan(
        repo,
        [
            _make_action("app.py", 8, MigrationActionStrategy.TEXT_EDIT,
                         "user.dict()", "user.model_dump()"),
        ],
    )
    original = (repo / "app.py").read_text(encoding="utf-8")

    result = execute_transformation_plan(plan)

    assert isinstance(result, TransformationResult)
    assert len(result.records) == 1
    rec = result.records[0]
    assert rec.status == TransformationStatus.SUCCESS
    assert rec.changed is True
    assert rec.strategy == MigrationActionStrategy.TEXT_EDIT
    assert rec.file == "app.py"
    assert rec.error is None

    # The working copy was actually modified ...
    wc_app = Path(result.working_copy) / "app.py"
    wc_text = wc_app.read_text(encoding="utf-8")
    assert "user.model_dump()" in wc_text
    assert "user.dict()" not in wc_text

    # ... and the original repository is untouched.
    assert (repo / "app.py").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# 2. Successful AST edit
# ---------------------------------------------------------------------------

def test_successful_ast_edit(repo: Path) -> None:
    """AST_EDIT performs a targeted replacement validated by AST parsing."""
    # "@validator(\"name\")" is a literal substring on line 3.
    plan = _make_plan(
        repo,
        [
            _make_action("app.py", 3, MigrationActionStrategy.AST_EDIT,
                         "@validator(\"name\")", "@field_validator(\"name\")"),
        ],
    )
    original = (repo / "app.py").read_text(encoding="utf-8")

    result = execute_transformation_plan(plan)

    rec = result.records[0]
    assert rec.status == TransformationStatus.SUCCESS
    assert rec.changed is True
    assert rec.strategy == MigrationActionStrategy.AST_EDIT

    wc_text = (Path(result.working_copy) / "app.py").read_text(encoding="utf-8")
    assert "@field_validator(\"name\")" in wc_text
    assert "@validator(\"name\")" not in wc_text
    # The transformed file must remain syntactically valid Python.
    ast.parse(wc_text)
    # Original repository untouched.
    assert (repo / "app.py").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# 3. Manual-review action
# ---------------------------------------------------------------------------

def test_manual_review_action(repo: Path) -> None:
    """MANUAL_REVIEW is skipped and recorded, without touching files."""
    original = (repo / "app.py").read_text(encoding="utf-8")
    plan = _make_plan(
        repo,
        [
            _make_action("app.py", 5, MigrationActionStrategy.MANUAL_REVIEW,
                         "Model __eq__ (V1 semantics)",
                         "Model __eq__ (V2 semantics)",
                         change_type=ChangeType.BEHAVIOR),
        ],
    )

    result = execute_transformation_plan(plan)

    assert result.success is True  # skipped != failed
    rec = result.records[0]
    assert rec.status == TransformationStatus.SKIPPED
    assert rec.changed is False
    assert rec.strategy == MigrationActionStrategy.MANUAL_REVIEW
    assert rec.error is not None
    assert "review" in rec.error.lower()
    # File unchanged in the working copy and the original.
    assert (Path(result.working_copy) / "app.py").read_text(encoding="utf-8") == original
    assert (repo / "app.py").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# 4. Failed transformation (source changed since discovery)
# ---------------------------------------------------------------------------

def test_failed_transformation_target_missing(repo: Path) -> None:
    """When the replacement target is absent the action fails and is recorded."""
    original = (repo / "app.py").read_text(encoding="utf-8")
    plan = _make_plan(
        repo,
        [
            # "old" text is deliberately not present in the file.
            _make_action("app.py", 8, MigrationActionStrategy.TEXT_EDIT,
                         "ThisTextDoesNotExist", "replacement"),
        ],
    )

    result = execute_transformation_plan(plan)

    assert result.success is False
    rec = result.records[0]
    assert rec.status == TransformationStatus.FAILED
    assert rec.changed is False
    assert rec.error is not None
    assert "source changed" in rec.error.lower() or "not found" in rec.error.lower()
    # Nothing written: working copy and original both pristine.
    assert (Path(result.working_copy) / "app.py").read_text(encoding="utf-8") == original
    assert (repo / "app.py").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# 5. Unchanged repository when a transformation fails (syntax error revert)
# ---------------------------------------------------------------------------

def test_repository_unchanged_on_ast_syntax_failure(repo: Path) -> None:
    """A syntax-introducing AST_EDIT is reverted; repo + wc stay pristine."""
    original = (repo / "app.py").read_text(encoding="utf-8")
    # Replacing "user.dict()" (which includes its closing paren) with an
    # unclosed call produces a syntax error -> must be reverted.
    plan = _make_plan(
        repo,
        [
            _make_action("app.py", 8, MigrationActionStrategy.AST_EDIT,
                         "user.dict()", "user.model_dump("),
        ],
    )

    result = execute_transformation_plan(plan)

    rec = result.records[0]
    assert rec.status == TransformationStatus.FAILED
    assert rec.changed is False
    assert rec.error is not None
    assert "syntax error" in rec.error.lower()
    # Working copy reverted to the pre-edit content ...
    wc_app = Path(result.working_copy) / "app.py"
    assert wc_app.read_text(encoding="utf-8") == original
    assert ast.parse(wc_app.read_text(encoding="utf-8")) is not None  # still valid
    # ... and the original repository is byte-for-byte unchanged.
    assert (repo / "app.py").read_text(encoding="utf-8") == original


def test_original_repository_never_corrupted(repo: Path) -> None:
    """Across a mixed plan of successes, skips, and failures the source repo
    must remain byte-for-byte identical (engine only touches the working copy)."""
    original = (repo / "app.py").read_text(encoding="utf-8")
    snapshot = (repo / "app.py").read_bytes()
    plan = _make_plan(
        repo,
        [
            _make_action("app.py", 3, MigrationActionStrategy.AST_EDIT,
                         "@validator(\"name\")", "@field_validator(\"name\")"),
            _make_action("app.py", 8, MigrationActionStrategy.TEXT_EDIT,
                         "user.dict()", "user.model_dump()"),
            _make_action("app.py", 3, MigrationActionStrategy.MANUAL_REVIEW,
                         "x", "y", change_type=ChangeType.BEHAVIOR),
            _make_action("app.py", 3, MigrationActionStrategy.LLM_ASSISTED,
                         "z", "z2"),
            _make_action("app.py", 8, MigrationActionStrategy.TEXT_EDIT,
                         "DoesNotExist", "whatever"),
        ],
    )

    result = execute_transformation_plan(plan)

    # Original bytes untouched.
    assert (repo / "app.py").read_bytes() == snapshot
    # Working copy is a distinct path.
    assert Path(result.working_copy).resolve() != repo.resolve()
    # One record per action, in order.
    assert len(result.records) == len(plan.actions)
    statuses = [r.status for r in result.records]
    assert TransformationStatus.FAILED in statuses
    assert result.success is False


# ---------------------------------------------------------------------------
# 6. LLM-assisted deferred + NO_TRANSFORMATION no-op
# ---------------------------------------------------------------------------

def test_llm_assisted_is_pending(repo: Path) -> None:
    original = (repo / "app.py").read_text(encoding="utf-8")
    plan = _make_plan(
        repo,
        [
            _make_action("app.py", 8, MigrationActionStrategy.LLM_ASSISTED,
                         "user.dict()", "user.model_dump()"),
        ],
    )
    result = execute_transformation_plan(plan)
    rec = result.records[0]
    assert rec.status == TransformationStatus.PENDING
    assert rec.changed is False
    assert rec.error is not None
    assert "llm" in rec.error.lower()
    assert (Path(result.working_copy) / "app.py").read_text(encoding="utf-8") == original
    assert result.success is True  # pending does not count as failure


def test_no_transformation_is_successful_noop(repo: Path) -> None:
    plan = _make_plan(
        repo,
        [
            _make_action("app.py", 1, MigrationActionStrategy.NO_TRANSFORMATION,
                         None, None, change_type=ChangeType.BEHAVIOR),
        ],
    )
    result = execute_transformation_plan(plan)
    rec = result.records[0]
    assert rec.status == TransformationStatus.SUCCESS
    assert rec.changed is False
    assert rec.error is None
    assert result.success is True


# ---------------------------------------------------------------------------
# 7. File no longer exists
# ---------------------------------------------------------------------------

def test_file_no_longer_exists(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "live.py").write_text("x = 1\n", encoding="utf-8")

    # Pre-make a working copy and delete the target file in it to simulate the
    # file disappearing between discovery and execution.
    wc = tmp_path / "wc"
    shutil.copytree(repo, wc)
    (wc / "src" / "live.py").unlink()

    plan = _make_plan(
        repo,
        [
            _make_action("src/live.py", 1, MigrationActionStrategy.TEXT_EDIT,
                         "x = 1", "x = 2"),
        ],
    )
    result = execute_transformation_plan(plan, working_copy=wc)

    rec = result.records[0]
    assert rec.status == TransformationStatus.FAILED
    assert rec.changed is False
    assert rec.error is not None
    assert "no longer exists" in rec.error.lower()
    # The original repository still has the file.
    assert (repo / "src" / "live.py").read_text(encoding="utf-8") == "x = 1\n"
    assert not (wc / "src" / "live.py").exists()


# ---------------------------------------------------------------------------
# 8. Invalid edit (empty replacement target)
# ---------------------------------------------------------------------------

def test_invalid_edit_empty_target(repo: Path) -> None:
    """An action with an empty 'old' is an invalid edit, recorded as failed."""
    original = (repo / "app.py").read_text(encoding="utf-8")
    plan = _make_plan(
        repo,
        [
            _make_action("app.py", 8, MigrationActionStrategy.TEXT_EDIT,
                         "", "x"),
        ],
    )
    result = execute_transformation_plan(plan)
    rec = result.records[0]
    assert rec.status == TransformationStatus.FAILED
    assert rec.changed is False
    assert "invalid" in rec.error.lower()
    assert (repo / "app.py").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# 9. End-to-end on the bundled example repository
# ---------------------------------------------------------------------------

def test_end_to_end_example_repo(tmp_path: Path) -> None:
    """Full Milestone 1->5 wiring on example_repo: original must be untouched."""
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

    result = execute_transformation_plan(plan)

    # One record per planned action, in order.
    assert len(result.records) == len(plan.actions)
    # The working copy is distinct from the source repository.
    assert Path(result.working_copy).resolve() != repo.resolve()
    # At least one targeted change must have landed (e.g. @validator ->
    # @field_validator, whose old text is literal in app.py).
    assert any(r.changed for r in result.records), "expected at least one applied edit"

    wc_app = Path(result.working_copy) / "app.py"
    wc_text = wc_app.read_text(encoding="utf-8")
    ast.parse(wc_text)  # working copy stays valid Python
    assert "@field_validator(\"name\")" in wc_text

    # The source repository must be byte-for-byte unchanged.
    assert (repo / "app.py").read_bytes() == app_original
