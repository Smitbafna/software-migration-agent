"""Transformation execution (Milestone 5).

Pipeline::

    MigrationPlan
        |
        v
    Transformation Engine  (this module)
        |
        v
    working repository copy  +  TransformationResult

The engine takes a :class:`MigrationPlan` (produced by Milestone 4) and applies
its :class:`MigrationAction` objects to a *working copy* of the repository, so
the original repository is never mutated.  Every action is recorded with its
status, affected file, strategy, whether it changed anything, and any error.

Supported strategies for this milestone:

* ``TEXT_EDIT``      — targeted, deterministic text/structured replacement.
* ``AST_EDIT``       — targeted replacement validated by parsing the Python
                        AST before (drift detection) and after (syntax
                        verification) the edit; a syntax error causes the
                        change to be reverted so no broken file is left behind.
* ``MANUAL_REVIEW``  — skipped and recorded (``SKIPPED``).
* ``LLM_ASSISTED``   — deferred; recorded as pending (``PENDING``).  No LLM
                        integration is implemented yet.
* ``NO_TRANSFORMATION`` — informational only; recorded as skipped ``SKIPPED``.

Edits are *targeted*: the occurrence nearest the discovered line is substituted
and only the affected file is rewritten.  Files whose ``old`` text is absent
(the source changed since discovery), that no longer exist, or that would be
left syntactically invalid are not corruptly rewritten — the engine records a
``FAILED`` outcome and leaves the working copy consistent.
"""

from __future__ import annotations

import ast
import shutil
import tempfile
from pathlib import Path

from .models import (
    MigrationAction,
    MigrationActionStrategy,
    MigrationPlan,
    TransformationRecord,
    TransformationResult,
    TransformationStatus,
)


# ---------------------------------------------------------------------------
# Working-copy management
# ---------------------------------------------------------------------------

def _resolve_repo(plan: MigrationPlan, repo_path: str | Path | None) -> Path:
    """Determine the source repository path for a plan."""
    if repo_path is not None:
        return Path(repo_path)
    return Path(plan.spec.repository)


def _create_working_copy(repo: Path) -> Path:
    """Copy a repository into a fresh temporary directory.

    The copy is independent of the original, so subsequent edits cannot corrupt
    the source repository.  The whole tree (source files, pyproject.toml,
    requirements, etc.) is copied verbatim.
    """
    src = repo.resolve()
    dest_parent = Path(tempfile.mkdtemp(prefix="migration_wc_"))
    dest = dest_parent / src.name
    shutil.copytree(src, dest)
    return dest


def _resolve_target(working_copy: Path, rel: str) -> Path:
    """Resolve a repo-relative ``file`` path under the working copy.

    Raises ``ValueError`` if the resolved path escapes the working copy (path
    traversal protection).
    """
    base = working_copy.resolve()
    target = (working_copy / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError as err:  # pragma: no cover - defensive
        raise ValueError(f"Target path escapes working copy: {rel}") from err
    return target


# ---------------------------------------------------------------------------
# Targeted text replacement
# ---------------------------------------------------------------------------

def _occurrence_line(content: str, index: int) -> int:
    """1-indexed line number of the character at ``index`` in ``content``."""
    return content.count("\n", 0, index) + 1


def _locate_occurrence(content: str, needle: str, line_no: int) -> int | None:
    """Return the start index of the ``needle`` occurrence nearest ``line_no``.

    Searching by proximity to the discovered line makes edits land at the right
    location even when a fragment appears more than once, and returns ``None``
    when the fragment is absent at all — the signal that the source changed
    since discovery.
    """
    if not needle:
        return None
    best_idx: int | None = None
    best_dist: int | None = None
    start = 0
    while True:
        idx = content.find(needle, start)
        if idx == -1:
            break
        dist = abs(_occurrence_line(content, idx) - line_no)
        if best_dist is None or dist < best_dist:
            best_idx = idx
            best_dist = dist
            if dist == 0:
                break
        start = idx + 1
    return best_idx


def _apply_text_replacement(
    content: str, old: str, new: str | None, line_no: int
) -> tuple[str, bool, str | None]:
    """Replace the occurrence of ``old`` nearest ``line_no`` with ``new``.

    Returns ``(new_content, changed, error)``.  Only the targeted occurrence is
    substituted; the rest of the file is untouched.  ``changed`` is ``True``
    only when a substitution actually happened.
    """
    if not old:
        return content, False, "Invalid edit: no replacement target (old text is empty)."
    if new is None:
        return content, False, "Invalid edit: no replacement text (new is None)."
    idx = _locate_occurrence(content, old, line_no)
    if idx is None:
        return content, False, (
            "Source changed since discovery: replacement target not found "
            f"near line {line_no}."
        )
    replaced = content[:idx] + new + content[idx + len(old):]
    return replaced, True, None


# ---------------------------------------------------------------------------
# Per-strategy execution
# ---------------------------------------------------------------------------

def _effective(old: str | None, change_old: str | None) -> str | None:
    """Resolve the text to replace, falling back to the originating change."""
    return old if old is not None else change_old


def _execute_text_edit(
    action: MigrationAction, target: Path, line_no: int, old: str | None, new: str | None
) -> tuple[bool, str | None]:
    """TEXT_EDIT: targeted deterministic text replacement."""
    if not target.exists():
        return False, f"File no longer exists: {target}"
    content = target.read_text(encoding="utf-8")
    new_content, changed, error = _apply_text_replacement(content, old or "", new, line_no)
    if changed:
        target.write_text(new_content, encoding="utf-8")
    return changed, error


def _execute_ast_edit(
    action: MigrationAction, target: Path, line_no: int, old: str | None, new: str | None
) -> tuple[bool, str | None]:
    """AST_EDIT: targeted replacement with structural (AST) verification.

    1. The file must exist and parse *before* the edit — if parsing fails now,
       the source changed since discovery (the file was structurally verified
       at discovery time).
    2. The targeted replacement is applied.
    3. The result must parse again — otherwise a syntax error was introduced
       and the edit is reverted so the working copy is left consistent.
    """
    if not target.exists():
        return False, f"File no longer exists: {target}"
    content = target.read_text(encoding="utf-8")

    # (1) Pre-edit structural check: source changed since discovery.
    try:
        ast.parse(content, filename=str(target))
    except SyntaxError as err:
        return False, (
            f"Source changed since discovery: file no longer parses "
            f"(line {err.lineno}: {err.msg})."
        )

    new_content, changed, error = _apply_text_replacement(content, old or "", new, line_no)
    if not changed:
        return False, error

    # (3) Post-edit structural check: revert on syntax error.
    try:
        ast.parse(new_content, filename=str(target))
    except SyntaxError as err:
        # Restore the pre-edit content so the working copy stays valid.
        target.write_text(content, encoding="utf-8")
        return False, (
            f"Syntax error after AST transformation "
            f"(line {err.lineno}: {err.msg}); edit reverted."
        )

    target.write_text(new_content, encoding="utf-8")
    return changed, None


def _execute_no_op(
    action: MigrationAction, target: Path, line_no: int, old: str | None, new: str | None
) -> tuple[bool, str | None]:
    """NO_TRANSFORMATION: no code edit is required (informational change)."""
    return False, None


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_STRATEGY_HANDLERS = {
    MigrationActionStrategy.TEXT_EDIT: _execute_text_edit,
    MigrationActionStrategy.AST_EDIT: _execute_ast_edit,
    MigrationActionStrategy.NO_TRANSFORMATION: _execute_no_op,
}

# Strategies that are intentionally not "executed" this milestone.
_TERMINAL_REASONS = {
    MigrationActionStrategy.MANUAL_REVIEW: (
        TransformationStatus.SKIPPED,
        "Manual review required — skipped (no automated edit).",
    ),
    MigrationActionStrategy.LLM_ASSISTED: (
        TransformationStatus.PENDING,
        "LLM-assisted transformation not yet implemented — pending.",
    ),
}


def _record(
    action: MigrationAction,
    file_rel: str,
    strategy: MigrationActionStrategy,
    status: TransformationStatus,
    changed: bool,
    error: str | None,
) -> TransformationRecord:
    return TransformationRecord(
        action=action,
        file=file_rel,
        strategy=strategy,
        status=status,
        changed=changed,
        error=error,
    )


def _execute_action(action: MigrationAction, working_copy: Path) -> TransformationRecord:
    """Execute a single action against the working copy, returning its record."""
    strategy = action.strategy
    rel = action.usage.file
    line_no = action.usage.line

    old = _effective(action.old, action.usage.change.old)
    new = _effective(action.new, action.usage.change.new)

    # Strategies that are deferred / intentionally not automated this milestone.
    if strategy in _TERMINAL_REASONS:
        status, reason = _TERMINAL_REASONS[strategy]
        return _record(action, rel, strategy, status, False, reason)

    # Informational-only change: a successful no-op.
    if strategy == MigrationActionStrategy.NO_TRANSFORMATION:
        return _record(action, rel, strategy, TransformationStatus.SUCCESS, False, None)

    handler = _STRATEGY_HANDLERS.get(strategy)
    if handler is None:  # pragma: no cover - defensive
        return _record(
            action, rel, strategy, TransformationStatus.SKIPPED, False,
            f"Unsupported strategy {strategy.value} — skipped.",
        )

    try:
        target = _resolve_target(working_copy, rel)
    except ValueError as err:
        return _record(action, rel, strategy, TransformationStatus.FAILED, False, str(err))

    try:
        changed, error = handler(action, target, line_no, old, new)
    except (OSError, UnicodeDecodeError) as err:
        return _record(action, rel, strategy, TransformationStatus.FAILED, False, str(err))

    status = TransformationStatus.SUCCESS if error is None else TransformationStatus.FAILED
    return _record(action, rel, strategy, status, changed, error)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class TransformationEngine:
    """Executes a :class:`MigrationPlan` against a working copy of a repository.

    By default a fresh copy of the repository is created on the first
    :meth:`execute` call so the source repository is never modified.  Pass
    ``working_copy=`` to reuse an existing copy (useful for tests that want to
    pre-modify files to simulate drift).
    """

    def __init__(
        self,
        repo_path: str | Path | None = None,
        working_copy: str | Path | None = None,
    ) -> None:
        self._repo_path = Path(repo_path) if repo_path is not None else None
        self._working_copy = Path(working_copy) if working_copy is not None else None

    def execute(self, plan: MigrationPlan) -> TransformationResult:
        """Execute every action in ``plan`` against the working copy."""
        repo = _resolve_repo(plan, self._repo_path)
        if self._working_copy is not None:
            wc = self._working_copy
        else:
            wc = _create_working_copy(repo)
        wc = wc.resolve()

        records = [_execute_action(action, wc) for action in plan.actions]
        success = not any(
            r.status == TransformationStatus.FAILED for r in records
        )

        if not success:
            notes = [
                "One or more actions failed; the working copy reflects only the "
                "actions that succeeded (failed edits are reverted).",
            ]
        elif any(r.status == TransformationStatus.PENDING for r in records):
            notes = [
                "Some actions were deferred (LLM-assisted) and not yet applied.",
            ]
        else:
            notes = []

        return TransformationResult(
            plan=plan,
            working_copy=str(wc),
            records=records,
            success=success,
            notes=notes,
        )


def execute_transformation_plan(
    plan: MigrationPlan,
    *,
    repo_path: str | Path | None = None,
    working_copy: str | Path | None = None,
) -> TransformationResult:
    """Convenience wrapper around :class:`TransformationEngine` for one plan.

    :param plan: The :class:`MigrationPlan` to execute.
    :param repo_path: Optional explicit source repository path (defaults to
        ``plan.spec.repository``).
    :param working_copy: Optional existing working-copy path to operate on in
        place of creating a fresh copy (mainly for testing drift scenarios).
    :return: A :class:`TransformationResult` with one record per action.
    """
    engine = TransformationEngine(repo_path=repo_path, working_copy=working_copy)
    return engine.execute(plan)



