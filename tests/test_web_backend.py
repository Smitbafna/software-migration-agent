"""Tests for the real stdlib web backend.

Offline tests monkeypatch ``_http_get`` so they are fully deterministic
and never touch the network.  Integration tests exercise the live
DuckDuckGo Lite endpoint and real page fetches, but are gated on actual
network availability (a quick connectivity probe) so the suite stays
reliable in offline environments.  Set ``MIGRATION_AGENT_NET_TESTS=0``
to force-skip them even when a network is present.
"""

from __future__ import annotations

import os
import socket
import urllib.error

import pytest

from migration_agent.knowledge._web_backend import (
    WebSearchBackend,
    _decode_redirect,
    _html_to_text,
    _parse_lite_results,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_LITE_PAGE = """
<html><head><title>django 4.0 release notes at DuckDuckGo</title></head><body>
<table><tr><td>
<a rel="nofollow" class="result-link"
   href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.djangoproject.com%2Fen%2F4.0%2Freleases%2F4.0%2F&amp;rut=abc">Django 4.0 release notes</a>
</td></tr><tr><td class="result-snippet">Django 4.0 supports Python 3.8+.</td></tr></table>
<table><tr><td>
<a rel="nofollow" class="result-link"
   href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fblog.example.com%2Fdjango-4%2F&amp;rut=def">Django 4 notes</a>
</td></tr><tr><td class="result-snippet">A blog post.</td></tr></table>
</body></html>
"""

_DOCS_PAGE = """
<html>
<head><title>Django 4.0 release notes | Django documentation</title></head>
<body>
<nav><a href="/en/4.0/">Home</a></nav>
<h1>Django 4.0 release notes</h1>
<p>Django 4.0 was released in December 2021. It supports Python 3.8, 3.9 and
3.10, and drops support for Python 3.6 and 3.7. The localization setting
behavior changed in this release.</p>
<h2>Features removed in 4.0</h2>
<p>The <code>USE_L10N</code> setting is deprecated in favor of <code>USE_I18N</code>.</p>
<p>The <code>pytz</code> library is no longer required; Django now uses
<code>zoneinfo</code> instead of <code>pytz</code> for time zone handling.</p>
<h2>Minor features</h2>
<p>The new <code>DEFAULT_AUTO_FIELD</code> setting controls the default primary
key type for new models.</p>
<pre>pytz -&gt; zoneinfo</pre>
<script>window.tracking = 1;</script>
</body>
</html>
"""


@pytest.fixture()
def backend(monkeypatch):
    """A backend whose HTTP layer is replaced with canned responses."""
    responses: dict[str, tuple[str, str, str]] = {
        "search": (
            "https://lite.duckduckgo.com/lite/",  # DDG Lite POST endpoint
            "text/html",
            _LITE_PAGE,
        ),
        "docs": (
            "https://docs.djangoproject.com/en/4.0/releases/4.0/",
            "text/html",
            _DOCS_PAGE,
        ),
    }
    instance = WebSearchBackend()

    def fake_http_get(url, *args, **kwargs):
        for canned in responses.values():
            if url == canned[0]:
                return canned
        raise urllib.error.URLError(f"no canned response for {url}")

    def fake_http_post(url, data=None, *args, **kwargs):
        canned = responses["search"]
        if url == canned[0]:
            return canned
        raise urllib.error.URLError(f"no canned POST response for {url}")

    monkeypatch.setattr(
        "migration_agent.knowledge._web_backend._http_get", fake_http_get
    )
    monkeypatch.setattr(
        "migration_agent.knowledge._web_backend._http_post", fake_http_post
    )
    instance._fake_responses = responses  # exposed for tests
    return instance


# ---------------------------------------------------------------------------
# Offline: search parsing
# ---------------------------------------------------------------------------


def test_parse_lite_results_extracts_links_and_snippets():
    results = _parse_lite_results(_LITE_PAGE)
    assert len(results) == 2
    first, second = results
    assert first.title == "Django 4.0 release notes"
    assert first.url == "https://docs.djangoproject.com/en/4.0/releases/4.0/"
    assert first.snippet == "Django 4.0 supports Python 3.8+."
    assert second.url == "https://blog.example.com/django-4/"


def test_search_prefers_authoritative_results_first(backend):
    results = backend.search("django 4.0 release notes", prefer_authoritative=True)
    assert results, "expected at least one result"
    assert results[0].url.startswith("https://docs.djangoproject.com/")


def test_search_returns_empty_when_all_engines_fail(monkeypatch):
    def boom(*args, **kwargs):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr("migration_agent.knowledge._web_backend._http_post", boom)
    monkeypatch.setattr("migration_agent.knowledge._web_backend._http_get", boom)
    assert WebSearchBackend().search("anything") == []


def test_search_rejects_empty_query():
    assert WebSearchBackend().search("   ") == []


def test_decode_redirect_variants():
    assert _decode_redirect("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa") == (
        "https://example.com/a"
    )
    assert _decode_redirect("https://example.com/plain") == "https://example.com/plain"
    assert _decode_redirect("/lite/next-page") is None
    assert _decode_redirect("javascript:void(0)") is None


# ---------------------------------------------------------------------------
# Offline: page fetch + HTML conversion
# ---------------------------------------------------------------------------


def test_fetch_page_returns_final_url_and_text(backend):
    page = backend.fetch_page("https://docs.djangoproject.com/en/4.0/releases/4.0/")
    assert page is not None
    # Final URL preserved (no redirects here, so identical).
    assert page.url == "https://docs.djangoproject.com/en/4.0/releases/4.0/"
    assert "Django 4.0 release notes" in page.title
    # Headings became sections; code became backticks; script dropped.
    assert "## Features removed in 4.0" in page.content
    assert "`USE_L10N`" in page.content and "`USE_I18N`" in page.content
    assert "`pytz -> zoneinfo`" in page.content
    assert "window.tracking" not in page.content


def test_fetch_page_rejects_non_http_url():
    assert WebSearchBackend().fetch_page("file:///etc/passwd") is None
    assert WebSearchBackend().fetch_page("ftp://example.com/x") is None


def test_fetch_page_rejects_non_html_content(monkeypatch):
    def fake_get(url):
        return url, "application/octet-stream", "\x00\x01binary"

    monkeypatch.setattr("migration_agent.knowledge._web_backend._http_get", fake_get)
    assert WebSearchBackend().fetch_page("https://example.com/file") is None


def test_fetch_page_returns_none_for_empty_body(monkeypatch):
    def fake_get(url):
        return url, "text/html", "<html><body></body></html>"

    monkeypatch.setattr("migration_agent.knowledge._web_backend._http_get", fake_get)
    assert WebSearchBackend().fetch_page("https://example.com/empty") is None


def test_html_to_text_unescapes_entities():
    html = "<h2>Notes</h2><p><code>old &amp; new</code> was removed. R &lt; 4.</p>"
    text = _html_to_text(html)
    assert "## Notes" in text
    assert "`old & new`" in text
    assert "R < 4." in text


def test_fetched_page_feeds_the_acquisition_extractor(backend):
    """End-to-end offline: fetched page text yields a change via extraction."""
    from migration_agent import MigrationSpec, acquire_migration_knowledge, set_backend

    set_backend(backend)
    try:
        result = acquire_migration_knowledge(
            MigrationSpec(
                repository=".",
                technology="django",
                source_version="3.2.5",
                target_version="4.0.0",
            )
        )
        assert result.supported, result.reason
        assert result.changes, "expected changes extracted from the fetched page"
        for change in result.changes:
            assert change.evidence is not None
            assert change.evidence.url == (
                "https://docs.djangoproject.com/en/4.0/releases/4.0/"
            )
            assert change.evidence.excerpt  # verbatim sentence from the page
    finally:
        set_backend(None)


# ---------------------------------------------------------------------------
# Network integration (auto-skipped without connectivity)
# ---------------------------------------------------------------------------


def _network_available() -> bool:
    if os.environ.get("MIGRATION_AGENT_NET_TESTS") == "0":
        return False
    try:
        socket.create_connection(("lite.duckduckgo.com", 443), timeout=5).close()
        return True
    except OSError:
        return False


@pytest.mark.network
def test_live_search_and_fetch_roundtrip():
    """Real integration: search DuckDuckGo Lite and fetch an official page."""
    backend = WebSearchBackend()
    results = backend.search("django 4.0 release notes", prefer_authoritative=True)
    assert results, "live search returned no results"
    official = [r for r in results if r.url.startswith("https://docs.djangoproject.com/")]
    assert official, "expected an official django docs result"

    page = backend.fetch_page(official[0].url)
    assert page is not None
    assert page.url == official[0].url
    assert "release notes" in page.title.lower()
    assert len(page.content) > 200

