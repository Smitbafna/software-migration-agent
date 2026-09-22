"""Affected-code discovery for Python repositories (Milestone 3).

Analyzes Python source files to locate usages relevant to a list of MigrationChanges.
Uses Python's stdlib AST to distinguish confirmed structural usages from textual candidates.
Ignores specified directories (.git, .venv, build, dist, node_modules, __pycache__).
Gracefully handles syntax errors by recording/skipping affected files and continuing analysis.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from .models import (
    AffectedUsage,
    MigrationChange,
    MigrationSpec,
    UsageClassification,
)

DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".eggs",
}


def _extract_source_context(lines: list[str], line_no: int, window: int = 2) -> str:
    """Return a small snippet of lines around line_no (1-indexed)."""
    idx = line_no - 1
    start = max(0, idx - window)
    end = min(len(lines), idx + window + 1)
    return "\n".join(lines[start:end])


def _get_symbols_for_change(change: MigrationChange) -> set[str]:
    """Extract key identifier tokens from a MigrationChange.old description."""
    if not change.old:
        return set()
    tokens = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", change.old))
    # Ignore python keywords / common noise words / base type names
    noise = {
        "cls", "self", "v", "obj", "def", "class", "True", "False", "None", "val", "f",
        "BaseModel", "Model", "Field", "Config", "semantics", "V1", "V2"
    }
    return tokens - noise


class _ASTUsageDetector(ast.NodeVisitor):
    """AST visitor that checks for structural occurrences of migration changes."""

    def __init__(self, change: MigrationChange):
        self.change = change
        self.change_old = change.old or ""
        self.confirmed_lines: set[int] = set()
        self.candidate_lines: set[int] = set()

    def visit_Call(self, node: ast.Call) -> None:
        # Check attribute calls (e.g. obj.parse_obj(), user.dict(), user.json())
        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if "parse_obj" in self.change_old and attr == "parse_obj":
                self.confirmed_lines.add(node.lineno)
            elif "dict()" in self.change_old and attr == "dict":
                self.confirmed_lines.add(node.lineno)
            elif "json()" in self.change_old and attr == "json":
                self.confirmed_lines.add(node.lineno)
            elif "__fields__" in self.change_old and attr in ("__fields__", "__fields_set__"):
                self.confirmed_lines.add(node.lineno)
        # Check function name calls (e.g. Field(regex=...), root_validator(...))
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id
            kw_names = {kw.arg for kw in node.keywords if kw.arg}
            if "Field(" in self.change_old and func_name == "Field" and "regex" in kw_names:
                self.confirmed_lines.add(node.lineno)
            elif "root_validator" in self.change_old and func_name == "root_validator" and "skip_on_failure" in kw_names:
                self.confirmed_lines.add(node.lineno)

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if "__fields__" in self.change_old and node.attr in ("__fields__", "__fields_set__"):
            self.confirmed_lines.add(node.lineno)
        elif "parse_obj" in self.change_old and node.attr == "parse_obj":
            self.confirmed_lines.add(node.lineno)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if "class Config:" in self.change_old or node.name == "Config":
            for stmt in node.body:
                # Class attribute assignment, e.g. orm_mode = True or allow_mutation = False
                targets = []
                if isinstance(stmt, ast.Assign):
                    targets = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
                elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    targets = [stmt.target.id]

                if "orm_mode" in self.change_old and "orm_mode" in targets:
                    self.confirmed_lines.add(stmt.lineno)
                if "allow_mutation" in self.change_old and "allow_mutation" in targets:
                    self.confirmed_lines.add(stmt.lineno)

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function_def(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function_def(node)
        self.generic_visit(node)

    def _check_function_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        dec_names = set()
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                dec_names.add(dec.id)
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    dec_names.add(dec.func.id)
                    kw_names = {kw.arg for kw in dec.keywords if kw.arg}
                    if "skip_on_failure" in self.change_old and "skip_on_failure" in kw_names:
                        self.confirmed_lines.add(node.lineno)
                elif isinstance(dec.func, ast.Attribute):
                    dec_names.add(dec.func.attr)

        if "validator" in self.change_old:
            if "validator" in dec_names or "root_validator" in dec_names:
                # Check for signature change rules
                param_names = [arg.arg for arg in node.args.args + node.args.kwonlyargs]
                if ("field" in self.change_old or "config" in self.change_old) and (
                    "field" in param_names or "config" in param_names
                ):
                    self.confirmed_lines.add(node.lineno)
                elif "@validator" in self.change_old:
                    self.confirmed_lines.add(node.lineno)

        if "__eq__" in self.change_old and node.name == "__eq__":
            self.candidate_lines.add(node.lineno)


def _analyze_file_for_change(
    file_path: Path,
    rel_path: str,
    lines: list[str],
    tree: ast.AST | None,
    change: MigrationChange,
) -> list[AffectedUsage]:
    """Search a single parsed Python file for usages of a given MigrationChange."""
    usages: list[AffectedUsage] = []
    symbols = _get_symbols_for_change(change)
    if not symbols:
        return usages

    confirmed_lines: set[int] = set()
    candidate_lines: set[int] = set()

    # Step 1: Structural AST matching when AST is available
    if tree is not None:
        detector = _ASTUsageDetector(change)
        detector.visit(tree)
        confirmed_lines = detector.confirmed_lines
        candidate_lines = detector.candidate_lines

    # Step 2: Line-by-line text match fallback
    # If a line contains matching symbols but AST did not confirm it structurally,
    # record it as a CANDIDATE (e.g. comment, string, or unverified name).
    for line_idx, line_str in enumerate(lines, start=1):
        if line_idx in confirmed_lines:
            usages.append(
                AffectedUsage(
                    change=change,
                    file=rel_path,
                    line=line_idx,
                    source_context=_extract_source_context(lines, line_idx),
                    classification=UsageClassification.CONFIRMED,
                )
            )
        elif line_idx in candidate_lines:
            usages.append(
                AffectedUsage(
                    change=change,
                    file=rel_path,
                    line=line_idx,
                    source_context=_extract_source_context(lines, line_idx),
                    classification=UsageClassification.CANDIDATE,
                )
            )
        else:
            # Check text matches for candidate classification
            for sym in symbols:
                if sym in line_str and not line_str.strip().startswith("#"):
                    # Check if symbol is present in text
                    # We classify text-only matches as CANDIDATE
                    usages.append(
                        AffectedUsage(
                            change=change,
                            file=rel_path,
                            line=line_idx,
                            source_context=_extract_source_context(lines, line_idx),
                            classification=UsageClassification.CANDIDATE,
                        )
                    )
                    break

    return usages


def discover_affected_usages(
    spec: MigrationSpec | str | Path,
    changes: list[MigrationChange],
    excluded_dirs: set[str] | None = None,
) -> list[AffectedUsage]:
    """Discover code locations across repository .py files affected by changes.

    :param spec: MigrationSpec or path to the target repository.
    :param changes: List of MigrationChanges to check.
    :param excluded_dirs: Directory names to ignore during traversal.
    :return: List of AffectedUsage records.
    """
    repo_path = Path(spec.repository) if isinstance(spec, MigrationSpec) else Path(spec)
    repo_path = repo_path.resolve()
    ignored = excluded_dirs if excluded_dirs is not None else DEFAULT_EXCLUDED_DIRS

    results: list[AffectedUsage] = []

    if not repo_path.exists():
        return results

    for root, dirs, files in os.walk(repo_path):
        # Filter directories in place to prevent scanning excluded folders
        dirs[:] = [
            d for d in dirs
            if d not in ignored and not d.startswith(".")
        ]

        for file in sorted(files):
            if not file.endswith(".py"):
                continue

            file_path = Path(root) / file
            rel_path = str(file_path.relative_to(repo_path))

            try:
                content = file_path.read_text(encoding="utf-8")
                lines = content.splitlines()
            except (OSError, UnicodeDecodeError) as err:
                continue

            # Attempt AST parse
            try:
                tree = ast.parse(content, filename=str(file_path))
                syntax_error = None
            except SyntaxError as err:
                tree = None
                syntax_error = err

            # Requirement 7: Handle syntax errors explicitly
            if syntax_error is not None:
                err_line = syntax_error.lineno or 1
                context = (
                    f"# SYNTAX ERROR in {rel_path} line {err_line}:\n"
                    f"# {syntax_error.msg}\n" + _extract_source_context(lines, err_line)
                )
                dummy_change = changes[0] if changes else MigrationChange(
                    change_type=None,  # type: ignore
                    description="File has syntax error",
                    evidence=None,  # type: ignore
                )
                results.append(
                    AffectedUsage(
                        change=dummy_change,
                        file=rel_path,
                        line=err_line,
                        source_context=context,
                        classification=UsageClassification.SYNTAX_ERROR,
                    )
                )
                continue

            # Requirement 2 & 5: Check each change against the AST / lines
            for change in changes:
                usages = _analyze_file_for_change(file_path, rel_path, lines, tree, change)
                results.extend(usages)

    return results
