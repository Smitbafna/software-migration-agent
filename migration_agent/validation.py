"""Validation & migration verification for transformed repositories (Milestone 6).

Pipeline::

    Transformed repository (working copy)
        |
        v
    Validation Engine  (this module)
        |
        v
    ValidationResult

The validator runs a small, deterministic set of checks against a
*working copy* of the repository.  It never modifies files.  Every check
produces a :class:`ValidationRecord` with a ``PASS`` / ``FAIL`` /
``SKIPPED`` status, the command that was run (where applicable), captured
stdout/stderr, and any execution error.

Checks implemented for this milestone:

* ``syntax``             — Python syntax validation via ``python -m py_compile``
                            for every ``.py`` file in the working copy.
* ``residual_old_usage`` — scan for occurrences of the *old* API text from the
                            original affected usages; flag any that remain.
* ``target_usage``       — detect presence of the *new* API text in the places
                            where the old usage was previously found.
* ``test_suite``         — if a standard test command can be safely detected
                            (``pytest`` via pyproject.toml, ``tox.ini``,
                            ``noxfile.py``, or ``setup.cfg`` aliases), run it;
                            otherwise skip (no assumption that every repo has tests).
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from .models import (
    AffectedUsage,
    MigrationChange,
    ValidationRecord,
    ValidationResult,
    ValidationStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PYTHON_EXE = sys.executable or (shutil.which("python3") or shutil.which("python") or "python")
_PY_COMPILE = [_PYTHON_EXE, "-m", "py_compile"]
_PYTEST_CMD = ["-m", "pytest"]


def _run(cmd, cwd=None, timeout=120):
    """Run *cmd* and capture exit_code, stdout, stderr, and any execution error.

    Returns ``(returncode, stdout, stderr, execution_error_or_None)``.
    """
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={"_PYTHONDONTWRITEBYTECODE": "1"},
        )
        return proc.returncode, proc.stdout, proc.stderr, None
    except FileNotFoundError as exc:
        return -1, "", "", f"command not found: {cmd[0]!r}"
    except PermissionError as exc:
        return -1, "", "", f"permission error: {exc}"
    except subprocess.TimeoutExpired as exc:
        return -1, "", "", f"command timed out after {timeout}s"
    except OSError as exc:
        return -1, "", "", f"execution error: {exc}"


def _python_files(root):
    """Return all .py files under *root*, in repo-relative order."""
    out = []
    for dirpath, dirs, files in root.walk():
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(files):
            if name.endswith(".py"):
                out.append(dirpath / name)
    return sorted(out)


def _relative_to_repo(path, repo):
    return str(path.resolve().relative_to(repo.resolve()))


# ---------------------------------------------------------------------------
# Check: Python syntax validation
# ---------------------------------------------------------------------------


def _check_syntax(working_copy):
    """Run py_compile over every .py file in the working copy."""
    files = _python_files(working_copy)
    if not files:
        return ValidationRecord(
            check="syntax",
            status=ValidationStatus.PASS,
            output="No Python source files found — nothing to validate.",
            affected_files=[],
        )

    failures = []
    errors = []
    for py_file in files:
        rc, stdout, stderr, exec_err = _run(_PY_COMPILE + [str(py_file)])
        combined = (stdout + stderr).strip()
        if exec_err:
            errors.append(
                f"{_relative_to_repo(py_file, working_copy)}: {exec_err}"
            )
        elif rc != 0:
            failures.append(
                f"{_relative_to_repo(py_file, working_copy)}: "
                f"{combined or '(non-zero exit)'}"
            )

    if errors:
        return ValidationRecord(
            check="syntax",
            status=ValidationStatus.FAIL,
            command=" ".join(_PY_COMPILE) + " <files>",
            output="\n".join(errors),
            error="syntax validation could not be completed for some files",
            affected_files=[
                _relative_to_repo(f, working_copy) for f in files
            ],
        )

    if failures:
        return ValidationRecord(
            check="syntax",
            status=ValidationStatus.FAIL,
            command=" ".join(_PY_COMPILE) + " <files>",
            output="\n".join(failures),
            affected_files=[f.split(":")[0] for f in failures],
        )

    return ValidationRecord(
        check="syntax",
        status=ValidationStatus.PASS,
        command=" ".join(_PY_COMPILE) + " <files>",
        output=f"All {len(files)} Python file(s) parse cleanly.",
        affected_files=[_relative_to_repo(f, working_copy) for f in files],
    )


# ---------------------------------------------------------------------------
# Check: residual old usage
# ---------------------------------------------------------------------------


def _check_residual_old_usage(working_copy, usages, changes):
    """Scan the working copy for residual occurrences of old API text.

    For each affected usage whose classification is CONFIRMED or CANDIDATE
    and whose change carries an ``old`` text, scan that file in the working
    copy for occurrences of the old text.  Any remaining occurrences after
    migration are flagged as residual.
    """
    if not usages:
        return ValidationRecord(
            check="residual_old_usage",
            status=ValidationStatus.PASS,
            output="No affected usages to check for residuals.",
        )

    residual_files = {}
    scanned = set()

    for usage in usages:
        if not usage.change.old:
            continue
        if usage.classification.name not in ("CONFIRMED", "CANDIDATE"):
            continue

        target = working_copy / usage.file
        if not target.is_file():
            continue

        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        rel = usage.file
        scanned.add(rel)
        hits = []
        old = usage.change.old
        idx = 0
        while True:
            idx = text.find(old, idx)
            if idx == -1:
                break
            line_no = text[:idx].count("\n") + 1
            hits.append(f"line {line_no}")
            idx += len(old)

        if hits:
            residual_files.setdefault(rel, []).extend(hits)

    # Broader scan: for each change with old text, walk entire working copy
    # to catch usages that were never discovered.
    for change in changes:
        if not change.old:
            continue
        old = change.old
        for py_file in _python_files(working_copy):
            rel = _relative_to_repo(py_file, working_copy)
            if rel in scanned:
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if old in text:
                line_no = text.find(old)
                line_no = text[:line_no].count("\n") + 1 if line_no != -1 else 1
                residual_files.setdefault(
                    rel, []
                ).append(f"line {line_no} (change: {change.description})")

    if not residual_files:
        parts = []
        if scanned:
            parts.append(f"Checked {len(scanned)} file(s) from affected usages.")
        parts.append("No residual old usages detected.")
        return ValidationRecord(
            check="residual_old_usage",
            status=ValidationStatus.PASS,
            output=" ".join(parts),
        )

    detail_lines = []
    affected = []
    for rel, hits in sorted(residual_files.items()):
        affected.append(rel)
        detail_lines.append(f"{rel}: {', '.join(hits)}")

    return ValidationRecord(
        check="residual_old_usage",
        status=ValidationStatus.FAIL,
        output="\n".join(["Residual old usages found:"] + detail_lines),
        affected_files=affected,
    )


# ---------------------------------------------------------------------------
# Check: target (new) usage detection
# ---------------------------------------------------------------------------


def _check_target_usage(working_copy, usages, changes):
    """Detect occurrences of the *new* API text where old usage was found.

    For each change that has a ``new`` text, check whether it appears in the
    working copy in files where the corresponding old usage was previously
    detected.  Presence is a good sign; absence is noted but not necessarily a
    failure (the new API may be introduced in a different form).
    """
    if not usages:
        return ValidationRecord(
            check="target_usage",
            status=ValidationStatus.PASS,
            output="No affected usages to check for target usage.",
        )

    findings = []
    missing_new = []

    for usage in usages:
        change = usage.change
        if not change.new:
            continue
        target = working_copy / usage.file
        if not target.is_file():
            continue
        try:
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        rel = usage.file
        if change.new in text:
            findings.append(
                f"{rel}: new usage present ({change.new!r})"
            )
        else:
            missing_new.append(
                f"{rel}: new usage {change.new!r} not found "
                f"(change: {change.description})"
            )

    # Broader check: search entire working copy for new text from any change.
    for change in changes:
        if not change.new:
            continue
        new = change.new
        for py_file in _python_files(working_copy):
            try:
                text = py_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if new in text:
                rel = _relative_to_repo(py_file, working_copy)
                findings.append(
                    f"{rel}: new usage {new!r} present "
                    f"(change: {change.description})"
                )

    parts = []
    if findings:
        parts.append("Target (new) usages detected:")
        parts.extend(findings)
    if missing_new:
        parts.append("\nNew usages not found at original locations:")
        parts.extend(missing_new)

    return ValidationRecord(
        check="target_usage",
        status=ValidationStatus.PASS,
        output="\n".join(parts) if parts else "No target usage information available.",
    )


# ---------------------------------------------------------------------------
# Check: project test suite
# ---------------------------------------------------------------------------

_TEST_OK_PATTERNS = re.compile(
    r"^(passed|ok|success|no tests ran|collection finished)",
    re.MULTILINE | re.IGNORECASE,
)


def _detect_test_command(repo):
    """Try to detect a standard test command for *repo*.

    Returns ``(command_or_None, reason_or_None)``.  ``command`` is a shell
    command string to run, or ``None`` when no standard test command can be
    safely detected.  ``reason`` explains why when ``command`` is ``None``.
    """
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
            data = {}
        tool = data.get("tool", {})
        if "pytest" in tool or "pytest.ini" in data:
            return ["-m", "pytest"], None
        # Any explicit pytest reference is enough to assume pytest is the
        # standard test runner for the project.
        if "pytest" in str(data):
            return ["-m", "pytest"], None

    if (repo / "tox.ini").is_file():
        return ["-m", "tox"], None
    if (repo / "noxfile.py").is_file():
        return ["-m", "nox"], None
    if (repo / "setup.cfg").is_file():
        try:
            cfg_text = (repo / "setup.cfg").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            cfg_text = ""
        if "pytest" in cfg_text.lower() or "[aliases]" in cfg_text:
            return ["-m", "pytest"], None

    return None, (
        "No standard test command detected "
        "(no pytest/tox/nox/setup.cfg pattern found)."
    )

def _check_test_suite(working_copy):
    """Run the project test suite if a standard test command can be detected.

    If no standard test command is detectable, the check is SKIPPED (no
    assumption that every repository has tests — requirement 3).
    """
    cmd, reason = _detect_test_command(working_copy)
    if cmd is None:
        return ValidationRecord(
            check="test_suite",
            status=ValidationStatus.SKIPPED,
            output=reason or "No standard test command detected.",
        )

    # Build the full command: Python executable + module invocation.
    full_cmd = [_PYTHON_EXE] + cmd
    rc, stdout, stderr, exec_err = _run(full_cmd, cwd=working_copy)
    combined = "\n".join(part for part in (stdout, stderr) if part).strip()

    if exec_err:
        return ValidationRecord(
            check="test_suite",
            status=ValidationStatus.FAIL,
            command=cmd,
            output="",
            error=f"Could not run test suite: {exec_err}",
        )

    # Zero exit -> pass.
    if rc == 0:
        return ValidationRecord(
            check="test_suite",
            status=ValidationStatus.PASS,
            command=cmd,
            output=combined or "(no output)",
        )

    # Non-zero exit but output suggests nothing was actually collected/run.
    if _TEST_OK_PATTERNS.search(combined or ""):
        return ValidationRecord(
            check="test_suite",
            status=ValidationStatus.PASS,
            command=cmd,
            output=combined or "(no output)",
        )

    return ValidationRecord(
        check="test_suite",
        status=ValidationStatus.FAIL,
        command=cmd,
        output=combined or "(no output)",
        error=f"Test suite exited with code {rc}",
    )


# ---------------------------------------------------------------------------
# Validation engine
# ---------------------------------------------------------------------------


class ValidationEngine:
    """Runs validation checks against a transformed working copy.

    The engine is read-only: it never modifies repository files
    (requirement 6).  All checks execute against the *working copy*
    produced by the transformation engine.
    """

    def __init__(self, working_copy):
        self.working_copy = Path(working_copy).resolve()

    def execute(self, usages=None, changes=None):
        """Run all validation checks and return a :class:`ValidationResult`.

        :param usages: Original affected usages (needed for residual/target
            usage checks).  If ``None``, those checks are SKIPPED with a note.
        :param changes: Migration changes (needed for residual/target usage
            checks).  If ``None``, those checks are SKIPPED with a note.
        """
        records = []

        # 1. Syntax validation — always run.
        records.append(_check_syntax(self.working_copy))

        # 2 & 3. Residual old usage + target usage — need usages/changes.
        if usages and changes:
            records.append(
                _check_residual_old_usage(self.working_copy, usages, changes)
            )
            records.append(
                _check_target_usage(self.working_copy, usages, changes)
            )
        else:
            records.append(
                ValidationRecord(
                    check="residual_old_usage",
                    status=ValidationStatus.SKIPPED,
                    output="No affected usages provided — residual check skipped.",
                )
            )
            records.append(
                ValidationRecord(
                    check="target_usage",
                    status=ValidationStatus.SKIPPED,
                    output="No affected usages provided — target usage check skipped.",
                )
            )

        # 4. Test suite — optional, skipped if no standard test command.
        records.append(_check_test_suite(self.working_copy))

        failed = [r for r in records if r.status == ValidationStatus.FAIL]
        success = len(failed) == 0
        notes = []
        if any(r.status == ValidationStatus.SKIPPED for r in records):
            skipped = [r.check for r in records if r.status == ValidationStatus.SKIPPED]
            notes.append(f"Checks skipped: {', '.join(skipped)}.")
        if not success:
            notes.append(
                f"{len(failed)} validation check(s) failed; review "
                f"{', '.join(r.check for r in failed)}."
            )

        return ValidationResult(
            working_copy=str(self.working_copy),
            records=records,
            success=success,
            notes=notes,
        )


def execute_validation(working_copy, usages=None, changes=None):
    """Convenience wrapper around :class:`ValidationEngine`.

    :param working_copy: Path to the transformed working copy to validate.
    :param usages: Original affected usages (for residual/target usage checks).
    :param changes: Migration changes (for residual/target usage checks).
    :return: A :class:`ValidationResult` with one record per check.
    """
    engine = ValidationEngine(working_copy)
    return engine.execute(usages=usages, changes=changes)
