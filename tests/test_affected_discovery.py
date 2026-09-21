"""Tests for Milestone 3 — Affected Code Discovery."""

import ast
from pathlib import Path
import pytest

from migration_agent import (
    ChangeType,
    Evidence,
    MigrationChange,
    MigrationSpec,
    UsageClassification,
    discover_affected_usages,
)


@pytest.fixture
def dummy_changes() -> list[MigrationChange]:
    evidence = Evidence(source="Test Docs", section="Usage", excerpt="parse_obj replaced")
    return [
        MigrationChange(
            change_type=ChangeType.REPLACEMENT,
            old="BaseModel.parse_obj(obj)",
            new="BaseModel.model_validate(obj)",
            description="parse_obj renamed to model_validate",
            evidence=evidence,
        ),
        MigrationChange(
            change_type=ChangeType.CONFIGURATION,
            old="class Config: orm_mode = True",
            new="model_config = ConfigDict(from_attributes=True)",
            description="orm_mode renamed to from_attributes",
            evidence=evidence,
        ),
        MigrationChange(
            change_type=ChangeType.REPLACEMENT,
            old="Field(regex=...)",
            new="Field(pattern=...)",
            description="regex renamed to pattern in Field",
            evidence=evidence,
        ),
    ]


def test_affected_discovery_fixture(tmp_path: Path, dummy_changes: list[MigrationChange]) -> None:
    # 1. Affected usage file
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    affected_file = src_dir / "models.py"
    affected_file.write_text(
        "from pydantic import BaseModel, Field\n"
        "class User(BaseModel):\n"
        "    name: str = Field(..., regex='^[A-Z]')\n"
        "    class Config:\n"
        "        orm_mode = True\n"
        "def load(data):\n"
        "    return User.parse_obj(data)\n",
        encoding="utf-8",
    )

    # 2. Unrelated usage file (plain comment/unrelated text)
    unrelated_file = src_dir / "unrelated.py"
    unrelated_file.write_text(
        "# This comment mentions parse_obj but has no code call\n"
        "def add(a, b):\n"
        "    return a + b\n",
        encoding="utf-8",
    )

    # 3. Multiple files (another affected file)
    another_file = src_dir / "helpers.py"
    another_file.write_text(
        "def parse_item(item):\n"
        "    return Item.parse_obj(item)\n",
        encoding="utf-8",
    )

    # 4. Excluded directory (.venv and build)
    venv_dir = tmp_path / ".venv" / "lib"
    venv_dir.mkdir(parents=True)
    (venv_dir / "ignored.py").write_text("User.parse_obj(data)\n", encoding="utf-8")

    build_dir = tmp_path / "build"
    build_dir.mkdir()
    (build_dir / "ignored.py").write_text("User.parse_obj(data)\n", encoding="utf-8")

    # 5. Syntax error file
    broken_file = src_dir / "syntax_error.py"
    broken_file.write_text("def broken_function(\n", encoding="utf-8")

    # Run discovery
    spec = MigrationSpec(
        repository=str(tmp_path),
        technology="pydantic",
        target_version="2",
    )

    usages = discover_affected_usages(spec, dummy_changes)

    # Assertions
    files_found = {u.file for u in usages}

    # Verify excluded directories were NOT scanned
    assert not any(".venv" in f for f in files_found)
    assert not any("build" in f for f in files_found)

    # Verify multiple valid files were scanned
    assert "src/models.py" in files_found
    assert "src/helpers.py" in files_found
    assert "src/syntax_error.py" in files_found

    # Verify syntax error classification
    syntax_error_usages = [u for u in usages if u.classification == UsageClassification.SYNTAX_ERROR]
    assert len(syntax_error_usages) == 1
    assert syntax_error_usages[0].file == "src/syntax_error.py"

    # Verify confirmed structural usages
    confirmed_usages = [u for u in usages if u.classification == UsageClassification.CONFIRMED]
    assert len(confirmed_usages) >= 3  # regex, orm_mode, parse_obj in models.py + parse_obj in helpers.py

    # Check source context is a small snippet, not entire file
    for u in usages:
        assert isinstance(u.source_context, str)
        assert len(u.source_context.splitlines()) <= 5
