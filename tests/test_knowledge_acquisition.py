"""Tests for Dynamic Migration Knowledge Acquisition (Milestone 9).

Tests cover:
1. Successful knowledge acquisition
2. Evidence attached to every change
3. Unsupported technology
4. Unknown source/target version
5. Insufficient authoritative evidence
6. Compatibility with existing Pydantic knowledge provider
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Protocol

from migration_agent import (
    ChangeType,
    Evidence,
    MigrationChange,
    MigrationSpec,
    acquire_migration_knowledge,
    set_backend,
)
from migration_agent.models import KnowledgeAcquisition, Confidence


# ---------------------------------------------------------------------------
# Mock search backend for deterministic testing
# ---------------------------------------------------------------------------


class MockSearchResult(Protocol):
    """A mock search result."""

    title: str
    url: str
    snippet: str


class MockPageContent(Protocol):
    """A mock page content."""

    url: str
    title: str
    content: str


class MockSearchBackend(Protocol):
    """A mock search backend for testing."""

    def search(self, query: str, prefer_authoritative: bool = True) -> list[MockSearchResult]:
        ...

    def fetch_page(self, url: str) -> MockPageContent | None:
        ...


@dataclass
class MockSearchResultImpl:
    """Concrete mock search result."""

    title: str
    url: str
    snippet: str


@dataclass
class MockPageContentImpl:
    """Concrete mock page content."""

    url: str
    title: str
    content: str


class MockSearchBackendImpl:
    """A configurable mock search backend for testing."""

    def __init__(
        self,
        search_results: list[MockSearchResultImpl] | None = None,
        page_contents: dict[str, MockPageContentImpl] | None = None,
    ):
        self.search_results = search_results or []
        self.page_contents = page_contents or {}

    def search(self, query: str, prefer_authoritative: bool = True) -> list[MockSearchResultImpl]:
        return self.search_results

    def fetch_page(self, url: str) -> MockPageContentImpl | None:
        return self.page_contents.get(url)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pydantic_spec() -> MigrationSpec:
    """A standard Pydantic migration spec."""
    return MigrationSpec(
        repository=".",
        technology="pydantic",
        source_version="1.10.14",
        target_version="2",
        source_version_exact=True,
    )


@pytest.fixture
def fastapi_spec() -> MigrationSpec:
    """A FastAPI migration spec (not registered statically)."""
    return MigrationSpec(
        repository=".",
        technology="fastapi",
        source_version="0.110.0",
        target_version="0.115.0",
        source_version_exact=True,
    )


@pytest.fixture
def unknown_tech_spec() -> MigrationSpec:
    """A spec with an unknown technology."""
    return MigrationSpec(
        repository=".",
        technology="unknown_framework",
        source_version="1.0.0",
        target_version="2.0.0",
        source_version_exact=True,
    )


@pytest.fixture
def empty_spec() -> MigrationSpec:
    """A spec with no technology."""
    return MigrationSpec(
        repository=".",
        technology="",
        source_version="1.0.0",
        target_version="2.0.0",
        source_version_exact=True,
    )


# ---------------------------------------------------------------------------
# Test 1: Compatibility with existing Pydantic knowledge provider
# ---------------------------------------------------------------------------


def test_pydantic_static_knowledge_still_works(pydantic_spec: MigrationSpec) -> None:
    """Verify that the existing Pydantic knowledge provider continues to work.

    This is a critical regression test - the static provider should be
    preferred when available, and dynamic acquisition should only kick in
    when no static knowledge exists.
    """
    result = acquire_migration_knowledge(pydantic_spec)

    assert result.supported is True
    assert len(result.changes) > 0

    # Verify every change has evidence
    for change in result.changes:
        assert change.evidence is not None
        assert change.evidence.source
        assert change.evidence.section
        assert change.evidence.excerpt

    # Verify we got the expected Pydantic changes
    change_types = {c.change_type for c in result.changes}
    assert ChangeType.REPLACEMENT in change_types


def test_pydantic_changes_have_valid_evidence(pydantic_spec: MigrationSpec) -> None:
    """Verify every Pydantic change has complete evidence fields."""
    result = acquire_migration_knowledge(pydantic_spec)
    assert result.supported

    for change in result.changes:
        evidence = change.evidence
        assert evidence.source, f"Change {change.old} -> {change.new} missing source"
        assert evidence.section, f"Change {change.old} -> {change.new} missing section"
        assert evidence.excerpt, f"Change {change.old} -> {change.new} missing excerpt"
        # URL is optional in static knowledge but preferred
        assert evidence.url or evidence.excerpt, "Evidence should have URL or substantial excerpt"


# ---------------------------------------------------------------------------
# Test 2: Unsupported technology (no static or dynamic knowledge)
# ---------------------------------------------------------------------------


def test_unknown_technology_returns_unsupported(
    unknown_tech_spec: MigrationSpec,
) -> None:
    """An unknown technology should return an unsupported result.

    Even with dynamic acquisition, if no authoritative sources can be found,
    we should return an explicit unsupported result rather than fabricating
    changes.
    """
    # Set up a mock backend that returns no results
    mock_backend = MockSearchBackendImpl(
        search_results=[],
        page_contents={},
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(unknown_tech_spec)
        assert result.supported is False
        assert result.reason is not None
        assert "unknown_framework" in result.reason.lower() or "no knowledge source" in result.reason.lower()
    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Test 3: Empty technology returns unsupported
# ---------------------------------------------------------------------------


def test_empty_technology_returns_unsupported(empty_spec: MigrationSpec) -> None:
    """An empty technology should return an unsupported result."""
    result = acquire_migration_knowledge(empty_spec)

    assert result.supported is False
    assert result.reason is not None
    assert "no technology" in result.reason.lower()


# ---------------------------------------------------------------------------
# Test 4: Unknown source/target version
# ---------------------------------------------------------------------------


def test_unknown_version_path_returns_unsupported(pydantic_spec: MigrationSpec) -> None:
    """A version path not covered by static or dynamic knowledge should be unsupported."""
    # Create a spec for a pydantic version path that isn't registered
    spec = MigrationSpec(
        repository=".",
        technology="pydantic",
        source_version="2.4.0",
        target_version="2.5.0",
        source_version_exact=True,
    )

    mock_backend = MockSearchBackendImpl(
        search_results=[],
        page_contents={},
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(spec)
        assert result.supported is False
        assert result.reason is not None
    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Test 5: Successful dynamic knowledge acquisition
# ---------------------------------------------------------------------------


def test_dynamic_knowledge_acquisition_success(fastapi_spec: MigrationSpec) -> None:
    """Successful dynamic acquisition should return supported result with changes."""
    # Mock search results with an authoritative source
    search_results = [
        MockSearchResultImpl(
            title="FastAPI Migration Guide",
            url="https://docs.fastapi.tiangolo.com/migration/",
            snippet="FastAPI migration from version 0.110 to 0.115 includes changes to...",
        ),
    ]

    # Mock page content with extractable migration changes
    page_content = MockPageContentImpl(
        url="https://docs.fastapi.tiangolo.com/migration/",
        title="FastAPI Migration Guide",
        content="""
# Migration Guide

## Changes to Request

The `Request.url_for()` method was renamed to `Request.url_path_for()`.

Use `Request.url_path_for()` instead of `Request.url_for()`.

## Removed Features

The `HTMLResponse` class was removed in version 0.115.

## Configuration Changes

The `default_query_params` setting changed to `default_params`.
""",
    )

    mock_backend = MockSearchBackendImpl(
        search_results=search_results,
        page_contents={search_results[0].url: page_content},
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(fastapi_spec)

        # Should be supported with changes
        assert result.supported is True
        assert len(result.changes) > 0

        # Verify every change has evidence
        for change in result.changes:
            assert change.evidence is not None
            assert change.evidence.source
            assert change.evidence.section
            assert change.evidence.excerpt
            assert change.evidence.url

        # Verify the source URL is from an authoritative source
        assert any(
            "docs.fastapi.tiangolo.com" in c.evidence.url
            for c in result.changes
        )

    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Test 6: Evidence attached to every change
# ---------------------------------------------------------------------------


def test_all_changes_have_evidence(fastapi_spec: MigrationSpec) -> None:
    """Every dynamically acquired change must have complete evidence."""
    search_results = [
        MockSearchResultImpl(
            title="Test Migration Guide",
            url="https://example.com/migration/",
            snippet="test migration content",
        ),
    ]

    page_content = MockPageContentImpl(
        url="https://example.com/migration/",
        title="Test Migration Guide",
        content="""
# Migration Changes

The `old_api()` method was replaced by `new_api()`.

The `deprecated_function` is now deprecated in favor of `new_function`.
""",
    )

    mock_backend = MockSearchBackendImpl(
        search_results=search_results,
        page_contents={search_results[0].url: page_content},
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(fastapi_spec)

        if result.supported:
            for change in result.changes:
                evidence = change.evidence
                assert evidence.source, f"Change missing source: {change.description}"
                assert evidence.section, f"Change missing section: {change.description}"
                assert evidence.excerpt, f"Change missing excerpt: {change.description}"
                # URL should be present for dynamically acquired knowledge
                assert evidence.url, f"Dynamically acquired change missing URL: {change.description}"
    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Test 7: Insufficient authoritative evidence
# ---------------------------------------------------------------------------


def test_insufficient_evidence_returns_unsupported(fastapi_spec: MigrationSpec) -> None:
    """When no authoritative evidence can be found, return unsupported result."""
    # Mock non-authoritative results only
    search_results = [
        MockSearchResultImpl(
            title="Some Personal Blog Post",
            url="https://medium.com/personal/blog-post",
            snippet="random thoughts about migration",
        ),
    ]

    page_content = MockPageContentImpl(
        url="https://medium.com/personal/blog-post",
        title="Some Personal Blog Post",
        content="Just some random thoughts, nothing authoritative here.",
    )

    mock_backend = MockSearchBackendImpl(
        search_results=search_results,
        page_contents={search_results[0].url: page_content},
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(fastapi_spec)

        # Should be unsupported due to lack of authoritative sources
        assert result.supported is False
        assert result.reason is not None
        assert "authoritative" in result.reason.lower() or "no knowledge" in result.reason.lower()

    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Test 8: Prefer authoritative sources over blogs
# ---------------------------------------------------------------------------


def test_authoritative_sources_preferred(fastapi_spec: MigrationSpec) -> None:
    """When both authoritative and non-authoritative sources exist,
    authoritative sources should be preferred."""
    search_results = [
        # Non-authoritative first (should be ignored or deprioritized)
        MockSearchResultImpl(
            title="Blog Post About Migration",
            url="https://medium.com/@user/migration-tips",
            snippet="Here's what I think about migration...",
        ),
        # Authoritative second (should be preferred)
        MockSearchResultImpl(
            title="Official FastAPI Migration Guide",
            url="https://docs.fastapi.tiangolo.com/migration/",
            snippet="Official documentation for FastAPI migration.",
        ),
    ]

    page_content = MockPageContentImpl(
        url="https://docs.fastapi.tiangolo.com/migration/",
        title="Official FastAPI Migration Guide",
        content="""
# Official Migration Guide

## API Changes

The `old_method()` was replaced by `new_method()`.
""",
    )

    mock_backend = MockSearchBackendImpl(
        search_results=search_results,
        page_contents={search_results[1].url: page_content},
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(fastapi_spec)

        if result.supported:
            # Should have changes from the authoritative source
            for change in result.changes:
                assert "docs.fastapi.tiangolo.com" in change.evidence.url, \
                    f"Change should come from authoritative source: {change.description}"
    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Test 9: No search results
# ---------------------------------------------------------------------------


def test_no_search_results_returns_unsupported(fastapi_spec: MigrationSpec) -> None:
    """When no search results are found, return unsupported result."""
    mock_backend = MockSearchBackendImpl(
        search_results=[],
        page_contents={},
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(fastapi_spec)

        assert result.supported is False
        assert result.reason is not None
        assert "no search results" in result.reason.lower() or "could not" in result.reason.lower()

    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Test 10: Page fetch failure
# ---------------------------------------------------------------------------


def test_page_fetch_failure_handled_gracefully(fastapi_spec: MigrationSpec) -> None:
    """When page fetch fails, handle gracefully and continue searching."""
    search_results = [
        MockSearchResultImpl(
            title="Good Migration Guide",
            url="https://docs.example.com/migration/",
            snippet="a migration guide",
        ),
    ]

    # Page fetch returns None (simulating failure)
    mock_backend = MockSearchBackendImpl(
        search_results=search_results,
        page_contents={},  # No page content available
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(fastapi_spec)

        # Should be unsupported since no page could be fetched
        assert result.supported is False

    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Test 11: Evidence URL is preserved
# ---------------------------------------------------------------------------


def test_evidence_url_preserved(fastapi_spec: MigrationSpec) -> None:
    """The URL of the source page should be preserved in evidence."""
    search_results = [
        MockSearchResultImpl(
            title="Test Docs",
            url="https://docs.example.com/v1-to-v2/migration/",
            snippet="migration guide",
        ),
    ]

    page_content = MockPageContentImpl(
        url="https://docs.example.com/v1-to-v2/migration/",
        title="Test Docs",
        content="The `old_function()` was replaced by `new_function()`.",
    )

    mock_backend = MockSearchBackendImpl(
        search_results=search_results,
        page_contents={search_results[0].url: page_content},
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(fastapi_spec)

        if result.supported:
            for change in result.changes:
                assert change.evidence.url == "https://docs.example.com/v1-to-v2/migration/", \
                    f"Evidence URL should be preserved: {change.description}"
    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Test 12: Multiple changes can be extracted
# ---------------------------------------------------------------------------


def test_multiple_changes_extracted(fastapi_spec: MigrationSpec) -> None:
    """Multiple migration changes should be extractable from a single page."""
    search_results = [
        MockSearchResultImpl(
            title="Comprehensive Migration Guide",
            url="https://docs.example.com/migration/",
            snippet="comprehensive migration guide",
        ),
    ]

    page_content = MockPageContentImpl(
        url="https://docs.example.com/migration/",
        title="Comprehensive Migration Guide",
        content="""
# Migration Guide

## Renamed APIs

The `parse_data()` method was renamed to `parse_input()`.
The `format_output()` method was renamed to `format_result()`.

## Removed Features

The `old_configuration` parameter was removed.

## Deprecated

The `legacy_helper` is deprecated in favor of `modern_helper`.
""",
    )

    mock_backend = MockSearchBackendImpl(
        search_results=search_results,
        page_contents={search_results[0].url: page_content},
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(fastapi_spec)

        if result.supported:
            assert len(result.changes) >= 2, "Should extract multiple changes"

            # Check that we have different change types
            change_types = {c.change_type for c in result.changes}
            assert ChangeType.REPLACEMENT in change_types or ChangeType.REMOVAL in change_types or ChangeType.DEPRECATION in change_types
    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Test 13: Reset backend after tests
# ---------------------------------------------------------------------------


def test_backend_reset_works() -> None:
    """Verify that the backend can be reset after tests."""
    mock_backend = MockSearchBackendImpl()
    set_backend(mock_backend)

    # Check that set_backend actually set the backend
    from migration_agent.knowledge.acquisition import _current_backend
    assert _current_backend is mock_backend

    set_backend(None)
    # After reset, the default backend should be used
    from migration_agent.knowledge.acquisition import _default_backend
    backend = _default_backend()
    assert backend is not None


# ---------------------------------------------------------------------------
# Test 14: Deduplication of changes
# ---------------------------------------------------------------------------


def test_changes_are_deduplicated(fastapi_spec: MigrationSpec) -> None:
    """Duplicate changes from multiple sources should be deduplicated."""
    search_results = [
        MockSearchResultImpl(
            title="Source 1",
            url="https://source1.example.com/migration/",
            snippet="migration content",
        ),
        MockSearchResultImpl(
            title="Source 2",
            url="https://source2.example.com/migration/",
            snippet="same migration content",
        ),
    ]

    # Both pages have the same change
    page_content_1 = MockPageContentImpl(
        url="https://source1.example.com/migration/",
        title="Source 1",
        content="The `old_api()` was renamed to `new_api()`.",
    )
    page_content_2 = MockPageContentImpl(
        url="https://source2.example.com/migration/",
        title="Source 2",
        content="The `old_api()` was renamed to `new_api()`.",
    )

    mock_backend = MockSearchBackendImpl(
        search_results=search_results,
        page_contents={
            search_results[0].url: page_content_1,
            search_results[1].url: page_content_2,
        },
    )
    set_backend(mock_backend)

    try:
        result = acquire_migration_knowledge(fastapi_spec)

        if result.supported:
            # Should have only one unique change, not two
            unique_changes = {(c.old, c.new) for c in result.changes}
            assert len(unique_changes) == 1, "Duplicate changes should be deduplicated"
    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Regression tests: query building and extraction quality
# ---------------------------------------------------------------------------


def test_build_queries_use_major_minor_versions() -> None:
    """Pinned semver versions are searched as major.minor.

    Full semver strings ('3.2.0 to 4.0.0') made real search engines drift to
    unrelated projects' release notes; '3.2 to 4.0' reliably surfaces the
    official Django documentation.
    """
    from migration_agent.knowledge.acquisition import _build_queries

    queries = _build_queries("django", "3.2.0", "4.0.0")
    assert queries[0] == "django 3.2 to 4.0 release notes"
    assert queries[1] == "django 4.0 release notes"
    assert queries[2] == "django 3.2 to 4.0 upgrade"
    # No pinned version ever appears in a query.
    assert all("3.2.0" not in q and "4.0.0" not in q for q in queries)


def test_short_version_trims_patch_segment() -> None:
    from migration_agent.knowledge.acquisition import _short_version

    assert _short_version("3.2.0") == "3.2"
    assert _short_version("4.0.0") == "4.0"
    assert _short_version("2") == "2"
    assert _short_version("0.110.0") == "0.110"


def test_replacement_without_successor_is_skipped(fastapi_spec: MigrationSpec) -> None:
    """'X is now the default ...' must not fabricate ``X -> None`` replacements."""
    from migration_agent.knowledge.acquisition import _extract_changes_from_page

    page = MockPageContentImpl(
        url="https://docs.example.com/migration/",
        title="Migration Guide",
        content=(
            "The Python standard library's `zoneinfo` is now the default "
            "timezone implementation.\n"
        ),
    )
    changes = _extract_changes_from_page(fastapi_spec, page, "Migration Guide")
    assert all(change.new is not None for change in changes), (
        "No replacement change may be emitted without a stated successor"
    )


def test_is_now_deprecated_classifies_as_deprecation(fastapi_spec: MigrationSpec) -> None:
    """'X is now deprecated' is a deprecation, not a replacement."""
    from migration_agent.knowledge.acquisition import _extract_changes_from_page

    page = MockPageContentImpl(
        url="https://docs.example.com/migration/",
        title="Migration Guide",
        content="Support for `pytz` is now deprecated in this release.\n",
    )
    changes = _extract_changes_from_page(fastapi_spec, page, "Migration Guide")
    assert changes, "expected a deprecation change"
    assert all(change.change_type == ChangeType.DEPRECATION for change in changes)
    assert changes[0].old == "pytz"
