"""Migration planning and transformation strategy (Milestone 4).

Pipeline::

    MigrationSpec + MigrationChange[] + AffectedUsage[] -> MigrationPlan
                                                          └── MigrationAction[]

For each :class:`AffectedUsage` the planner examines the associated
:class:`MigrationChange`, the usage classification, and the evidence
backing the change, then assigns a transformation strategy.  The
resulting :class:`MigrationPlan` is a list of self-contained
:class:`MigrationAction` objects — **no repository files are modified**.
"""

from __future__ import annotations

from .models import (
    AffectedUsage,
    ChangeType,
    MigrationAction,
    MigrationActionStrategy,
    MigrationChange,
    MigrationPlan,
    MigrationSpec,
    UsageClassification,
)


def _decide_strategy(usage: AffectedUsage) -> tuple[MigrationActionStrategy, str]:
    """Choose a transformation strategy and reason for a single usage.

    The decision is driven by two orthogonal signals:

    * ``usage.classification`` — how confidently the usage was located
      (AST-verified ``CONFIRMED`` vs. text-only ``CANDIDATE`` vs.
      ``SYNTAX_ERROR`` file).
    * ``usage.change.change_type`` — the nature of the migration
      (replacement, configuration, removal, deprecation, signature,
      behavior).
    """
    change = usage.change

    # ------------------------------------------------------------------
    # Case: no transformation is needed.
    # A change that carries no concrete ``old`` / ``new`` code text is
    # purely informational; nothing in the source can be transformed.
    # ------------------------------------------------------------------
    if change.old is None and change.new is None:
        return (
            MigrationActionStrategy.NO_TRANSFORMATION,
            "No code transformation required: the change is informational only.",
        )

    # ------------------------------------------------------------------
    # Case: syntax error.
    # AST analysis is unavailable, so we cannot verify what the code
    # actually does.  A human must review the file first.
    # ------------------------------------------------------------------
    if usage.classification == UsageClassification.SYNTAX_ERROR:
        return (
            MigrationActionStrategy.MANUAL_REVIEW,
            "File has syntax errors; AST analysis unavailable, manual "
            "intervention required.",
        )

    # ------------------------------------------------------------------
    # Case: behavior change.
    # Behavior changes are semantic — the code may or may not need to
    # change, and that determination requires human judgment.
    # ------------------------------------------------------------------
    if change.change_type == ChangeType.BEHAVIOR:
        return (
            MigrationActionStrategy.MANUAL_REVIEW,
            "Behavior change: semantic difference requires manual review "
            "to determine code impact.",
        )

    # ------------------------------------------------------------------
    # Case: candidate (text-only match, not AST-verified).
    # Without structural verification the match could be a comment, a
    # string, or a coincidentally-named identifier; semantic validation
    # is required before a safe edit.
    # ------------------------------------------------------------------
    if usage.classification == UsageClassification.CANDIDATE:
        if change.change_type == ChangeType.REPLACEMENT:
            return (
                MigrationActionStrategy.LLM_ASSISTED,
                "Text-only match (not AST-verified); semantic verification "
                "needed before replacement.",
            )
        return (
            MigrationActionStrategy.LLM_ASSISTED,
            "Text-only match (not AST-verified); semantic review needed "
            "to determine safety.",
        )

    # ------------------------------------------------------------------
    # Case: confirmed (AST-verified structural match).
    # ------------------------------------------------------------------
    if usage.classification == UsageClassification.CONFIRMED:
        if change.change_type == ChangeType.REPLACEMENT:
            return (
                MigrationActionStrategy.TEXT_EDIT,
                "Confirmed simple replacement — deterministic text edit.",
            )
        if change.change_type == ChangeType.REMOVAL:
            return (
                MigrationActionStrategy.AST_EDIT,
                "Confirmed removal — structural edit to remove the obsolete API.",
            )
        if change.change_type == ChangeType.CONFIGURATION:
            return (
                MigrationActionStrategy.AST_EDIT,
                "Confirmed configuration change — structural edit to "
                "class/config structure.",
            )
        if change.change_type == ChangeType.DEPRECATION:
            return (
                MigrationActionStrategy.AST_EDIT,
                "Confirmed deprecation — structural edit to replace the "
                "deprecated decorator/API.",
            )
        if change.change_type == ChangeType.SIGNATURE:
            return (
                MigrationActionStrategy.AST_EDIT,
                "Confirmed signature change — structural edit to function "
                "signature.",
            )

    # ------------------------------------------------------------------
    # Fallback: ambiguous match.
    # If we reach here the classification or change type is unexpected;
    # the safe default is to escalate to a human.
    # ------------------------------------------------------------------
    return (
        MigrationActionStrategy.MANUAL_REVIEW,
        "Ambiguous match — could not determine a safe automated transformation.",
    )


def plan_action(usage: AffectedUsage) -> MigrationAction:
    """Plan a single transformation action for one :class:`AffectedUsage`.

    :param usage: The affected usage to plan for.
    :return: A :class:`MigrationAction` with strategy, reason, and the
        ``old`` / ``new`` replacement text surfaced from the change.
    """
    strategy, reason = _decide_strategy(usage)
    return MigrationAction(
        usage=usage,
        strategy=strategy,
        reason=reason,
        old=usage.change.old,
        new=usage.change.new,
    )


def create_migration_plan(
    spec: MigrationSpec,
    changes: list[MigrationChange],
    usages: list[AffectedUsage],
) -> MigrationPlan:
    """Build a :class:`MigrationPlan` from a spec, its changes, and usages.

    :param spec: The :class:`MigrationSpec` driving this plan.
    :param changes: All :class:`MigrationChange` objects known for this
        migration.  Changes with no corresponding :class:`AffectedUsage`
        (i.e. *no direct code usage*) naturally produce no actions.
    :param usages: All discovered :class:`AffectedUsage` objects to plan
        for.
    :return: A :class:`MigrationPlan` with one :class:`MigrationAction`
        per affected usage, plus any informational notes.
    """
    # No transformation needed when the spec itself says migration is
    # not required (or the source version cannot be determined).
    if not spec.migration_required:
        plan = MigrationPlan(spec=spec)
        plan.notes.append(
            "No migration required: source version matches target "
            "or cannot be determined."
        )
        return plan

    # Plan one action per affected usage.
    actions = [plan_action(usage) for usage in usages]
    plan = MigrationPlan(spec=spec, actions=actions)

    # Note changes that have no direct code usage in this repository.
    used_changes = {id(u.change) for u in usages}
    unused = [c for c in changes if id(c) not in used_changes]
    if unused:
        names = ", ".join(c.old or c.description for c in unused)
        plan.notes.append(
            f"{len(unused)} change(s) have no direct code usage in this "
            f"repository: {names}."
        )

    return plan
