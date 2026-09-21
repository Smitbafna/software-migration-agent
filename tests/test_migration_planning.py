"""Tests for Milestone 4 — Migration Planning & Transformation Strategy."""

import pytest

from migration_agent import (
    AffectedUsage,
    ChangeType,
    Confidence,
    Evidence,
    MigrationActionStrategy,
    MigrationChange,
    MigrationPlan,
    UsageClassification,
    create_migration_plan,
    plan_action,
)
from migration_agent.models import MigrationAction, MigrationSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_change(
    change_type: ChangeType,
    old: str | None,
    new: str | None,
    description: str = "test change",
    confidence: Confidence = Confidence.HIGH,
    evidence: Evidence | None = None,
) -> MigrationChange:
    if evidence is None:
        evidence = Evidence(source="Test Docs", section="Usage", excerpt="test excerpt")
    return MigrationChange(
        change_type=change_type,
        old=old,
        new=new,
        description=description,
        evidence=evidence,
        confidence=confidence,
    )


def _make_usage(
    change: MigrationChange,
    classification: UsageClassification = UsageClassification.CONFIRMED,
    line: int = 1,
    file: str = "test.py",
) -> AffectedUsage:
    return AffectedUsage(
        change=change,
        file=file,
        line=line,
        source_context=f"line {line}: example code",
        classification=classification,
    )


@pytest.fixture
def evidence() -> Evidence:
    return Evidence(
        source="Pydantic Migration Guide (V1 -> V2)",
        section="Changes to pydantic.BaseModel",
        excerpt="parse_obj() model_validate()",
        url="https://docs.pydantic.dev/2.10/migration/",
    )


@pytest.fixture
def spec() -> MigrationSpec:
    return MigrationSpec(
        repository=".",
        technology="pydantic",
        source_version="1.10.14",
        target_version="2",
        source_version_exact=True,
    )


# ---------------------------------------------------------------------------
# Strategy decision: deterministic / simple
# ---------------------------------------------------------------------------

def test_deterministic_simple_migration(evidence: Evidence) -> None:
    """CONFIRMED + REPLACEMENT -> TEXT_EDIT (simple deterministic change)."""
    change = MigrationChange(
        change_type=ChangeType.REPLACEMENT,
        old="BaseModel.parse_obj(obj)",
        new="BaseModel.model_validate(obj)",
        description="parse_obj renamed to model_validate",
        evidence=evidence,
    )
    usage = _make_usage(change, UsageClassification.CONFIRMED)

    action = plan_action(usage)

    assert isinstance(action, MigrationAction)
    assert action.strategy == MigrationActionStrategy.TEXT_EDIT
    assert action.old == "BaseModel.parse_obj(obj)"
    assert action.new == "BaseModel.model_validate(obj)"
    assert action.usage is usage
    assert "deterministic" in action.reason.lower()


# ---------------------------------------------------------------------------
# Strategy decision: AST-based
# ---------------------------------------------------------------------------

def test_ast_based_migration(evidence: Evidence) -> None:
    """CONFIRMED + CONFIGURATION -> AST_EDIT (structural change)."""
    change = MigrationChange(
        change_type=ChangeType.CONFIGURATION,
        old="class Config: orm_mode = True",
        new="model_config = ConfigDict(from_attributes=True)",
        description="orm_mode renamed to from_attributes",
        evidence=evidence,
    )
    usage = _make_usage(change, UsageClassification.CONFIRMED)

    action = plan_action(usage)

    assert action.strategy == MigrationActionStrategy.AST_EDIT
    assert "structural" in action.reason.lower()


def test_ast_based_removal(evidence: Evidence) -> None:
    """CONFIRMED + REMOVAL -> AST_EDIT (remove obsolete API)."""
    change = MigrationChange(
        change_type=ChangeType.REMOVAL,
        old="@root_validator(..., skip_on_failure=...)",
        new=None,
        description="skip_on_failure argument removed",
        evidence=evidence,
    )
    usage = _make_usage(change, UsageClassification.CONFIRMED)

    action = plan_action(usage)

    assert action.strategy == MigrationActionStrategy.AST_EDIT
    assert action.new is None  # nothing to replace with


def test_ast_based_signature_change(evidence: Evidence) -> None:
    """CONFIRMED + SIGNATURE -> AST_EDIT."""
    change = MigrationChange(
        change_type=ChangeType.SIGNATURE,
        old='@validator("f")\ndef f(cls, v, field, config)',
        new='@field_validator("f")\ndef f(cls, v, info: ValidationInfo)',
        description="validator signature changed",
        evidence=evidence,
    )
    usage = _make_usage(change, UsageClassification.CONFIRMED)

    action = plan_action(usage)
    assert action.strategy == MigrationActionStrategy.AST_EDIT


def test_ast_based_deprecation(evidence: Evidence) -> None:
    """CONFIRMED + DEPRECATION -> AST_EDIT."""
    change = MigrationChange(
        change_type=ChangeType.DEPRECATION,
        old="@validator",
        new="@field_validator",
        description="@validator deprecated",
        evidence=evidence,
    )
    usage = _make_usage(change, UsageClassification.CONFIRMED)

    action = plan_action(usage)
    assert action.strategy == MigrationActionStrategy.AST_EDIT


# ---------------------------------------------------------------------------
# Strategy decision: ambiguous / manual review
# ---------------------------------------------------------------------------

def test_ambiguous_migration_llm_assisted(evidence: Evidence) -> None:
    """CANDIDATE (text-only match, not AST-verified) -> LLM_ASSISTED."""
    change = MigrationChange(
        change_type=ChangeType.REPLACEMENT,
        old="BaseModel.parse_obj(obj)",
        new="BaseModel.model_validate(obj)",
        description="parse_obj renamed to model_validate",
        evidence=evidence,
    )
    usage = _make_usage(change, UsageClassification.CANDIDATE)

    action = plan_action(usage)

    assert action.strategy == MigrationActionStrategy.LLM_ASSISTED
    assert "not AST-verified" in action.reason


def test_manual_review_syntax_error(evidence: Evidence) -> None:
    """SYNTAX_ERROR -> MANUAL_REVIEW (cannot verify structurally)."""
    change = MigrationChange(
        change_type=ChangeType.REPLACEMENT,
        old="BaseModel.parse_obj(obj)",
        new="BaseModel.model_validate(obj)",
        description="parse_obj renamed to model_validate",
        evidence=evidence,
    )
    usage = _make_usage(change, UsageClassification.SYNTAX_ERROR)

    action = plan_action(usage)

    assert action.strategy == MigrationActionStrategy.MANUAL_REVIEW
    assert "syntax" in action.reason.lower()


def test_manual_review_behavior_change(evidence: Evidence) -> None:
    """CONFIRMED + BEHAVIOR -> MANUAL_REVIEW (semantic, ambiguous)."""
    change = MigrationChange(
        change_type=ChangeType.BEHAVIOR,
        old="Model __eq__ (V1 semantics)",
        new="Model __eq__ (V2 semantics)",
        description="Equality semantics tightened in V2",
        evidence=evidence,
    )
    usage = _make_usage(change, UsageClassification.CONFIRMED)

    action = plan_action(usage)

    assert action.strategy == MigrationActionStrategy.MANUAL_REVIEW
    assert "behavior" in action.reason.lower()


def test_no_transformation_needed() -> None:
    """Change with old=None and new=None -> NO_TRANSFORMATION."""
    change = MigrationChange(
        change_type=ChangeType.BEHAVIOR,
        old=None,
        new=None,
        description="Internal documentation note — no code change",
        evidence=Evidence(source="Docs", section="Note", excerpt="info"),
    )
    usage = _make_usage(change, UsageClassification.CANDIDATE)

    action = plan_action(usage)

    assert action.strategy == MigrationActionStrategy.NO_TRANSFORMATION
    assert "informational" in action.reason.lower()


# ---------------------------------------------------------------------------
# Full plan creation
# ---------------------------------------------------------------------------

def test_create_migration_plan_mixed(spec: MigrationSpec, evidence: Evidence) -> None:
    """Plan with mixed usages produces one action per usage in order."""
    repl_change = MigrationChange(
        change_type=ChangeType.REPLACEMENT,
        old="BaseModel.parse_obj(obj)",
        new="BaseModel.model_validate(obj)",
        description="parse_obj -> model_validate",
        evidence=evidence,
    )
    cfg_change = MigrationChange(
        change_type=ChangeType.CONFIGURATION,
        old="class Config: orm_mode = True",
        new="model_config = ConfigDict(from_attributes=True)",
        description="orm_mode -> from_attributes",
        evidence=evidence,
    )
    cand_change = MigrationChange(
        change_type=ChangeType.REPLACEMENT,
        old="BaseModel.parse_obj(obj)",
        new="BaseModel.model_validate(obj)",
        description="parse_obj -> model_validate",
        evidence=evidence,
    )

    usages = [
        _make_usage(repl_change, UsageClassification.CONFIRMED, line=10),
        _make_usage(cfg_change, UsageClassification.CONFIRMED, line=15),
        _make_usage(cand_change, UsageClassification.CANDIDATE, line=20),
    ]

    plan = create_migration_plan(spec, [repl_change, cfg_change], usages)

    assert isinstance(plan, MigrationPlan)
    assert len(plan.actions) == 3
    assert plan.actions[0].strategy == MigrationActionStrategy.TEXT_EDIT
    assert plan.actions[1].strategy == MigrationActionStrategy.AST_EDIT
    assert plan.actions[2].strategy == MigrationActionStrategy.LLM_ASSISTED


def test_plan_no_migration_required(evidence: Evidence) -> None:
    """When source == target, plan is empty with a note."""
    spec = MigrationSpec(
        repository=".",
        technology="pydantic",
        source_version="2",
        target_version="2",
        source_version_exact=True,
    )
    change = _make_change(
        ChangeType.REPLACEMENT, "old_api()", "new_api()", evidence=evidence
    )
    usage = _make_usage(change)

    plan = create_migration_plan(spec, [change], [usage])

    assert len(plan.actions) == 0
    assert "No migration required" in plan.notes[0]


def test_plan_no_direct_code_usage(spec: MigrationSpec, evidence: Evidence) -> None:
    """Changes with no affected usages are noted but produce no actions."""
    used_change = MigrationChange(
        change_type=ChangeType.REPLACEMENT,
        old="BaseModel.parse_obj(obj)",
        new="BaseModel.model_validate(obj)",
        description="parse_obj -> model_validate",
        evidence=evidence,
    )
    unused_change = MigrationChange(
        change_type=ChangeType.REPLACEMENT,
        old="Model.dict()",
        new="Model.model_dump()",
        description="dict -> model_dump",
        evidence=evidence,
    )
    usage = _make_usage(used_change, UsageClassification.CONFIRMED, line=5)

    plan = create_migration_plan(spec, [used_change, unused_change], [usage])

    assert len(plan.actions) == 1
    assert "no direct code usage" in plan.notes[0]
    assert "dict" in plan.notes[0].lower() or "model_dump" in plan.notes[0]


def test_plan_empty_usages(spec: MigrationSpec, evidence: Evidence) -> None:
    """Empty usages list -> empty plan with no-direct-usage note."""
    change = MigrationChange(
        change_type=ChangeType.REPLACEMENT,
        old="BaseModel.parse_obj(obj)",
        new="BaseModel.model_validate(obj)",
        description="parse_obj -> model_validate",
        evidence=evidence,
    )

    plan = create_migration_plan(spec, [change], [])

    assert len(plan.actions) == 0
    assert len(plan.notes) == 1
    assert "no direct code usage" in plan.notes[0]
