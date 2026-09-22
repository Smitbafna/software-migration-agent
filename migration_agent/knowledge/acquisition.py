"""Dynamic migration knowledge acquisition from authoritative web documentation.

This module discovers migration knowledge from authoritative sources (official
migration guides, release notes, documentation) using web search, and extracts
evidence-backed MigrationChange objects.

Key design principles:
- Isolate web/search access behind a small interface for testability
- Prefer authoritative sources over arbitrary blogs
- Every change must have verifiable evidence (source, section, excerpt, URL)
- Don't trust search snippets blindly - inspect source pages
- Return explicit unsupported result when authoritative info can't be found
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Iterator
from typing import Protocol

from ..models import ChangeType, Evidence, MigrationChange, MigrationSpec

# ---------------------------------------------------------------------------
# Search/Fetch interface – isolated so it can be mocked in tests
# ---------------------------------------------------------------------------


class PageContent(Protocol):
    """A retrieved web page with its canonical URL."""

    url: str
    title: str
    content: str


class SearchResult(Protocol):
    """A single web search result."""

    title: str
    url: str
    snippet: str


class SearchBackend(Protocol):
    """Interface for web search and page retrieval.

    Implementations can be swapped for tests (e.g. a mock that returns
    canned results) without touching the acquisition logic.
    """

    def search(self, query: str, prefer_authoritative: bool = True) -> list[SearchResult]:
        """Search the web for ``query``.

        When ``prefer_authoritative`` is True, results should be ranked so
        that official documentation, migration guides, and release notes
        appear before arbitrary blogs.
        """
        ...

    def fetch_page(self, url: str) -> PageContent | None:
        """Retrieve and parse a single page.

        Returns ``None`` when the page cannot be fetched or parsed.
        """


# ---------------------------------------------------------------------------
# Simple built-in search backend using the available web tools
# ---------------------------------------------------------------------------

_current_backend: SearchBackend | None = None


def set_backend(backend: SearchBackend | None) -> None:
    """Replace the search backend (used in tests to inject a mock)."""
    global _current_backend
    _current_backend = backend


def _default_backend() -> SearchBackend:
    """Lazy-initialize the real web-search backend on first use."""
    global _current_backend
    if _current_backend is not None:
        return _current_backend
    from ._web_backend import WebSearchBackend
    _current_backend = WebSearchBackend()
    return _current_backend


# ---------------------------------------------------------------------------
# Source classification – decide whether a result looks authoritative
# ---------------------------------------------------------------------------

_AUTHORITATIVE_HOSTS = frozenset([
    "docs.pydantic.dev",
    "docs.python.org",
    "docs.djangoproject.com",
    "docs.fastapi.tiangolo.com",
    "fastapi.tiangolo.com",
    "flask.palletsprojects.com",
    "djangoproject.com",
    "python.org",
    "github.com",
    "devblogs.microsoft.com",
    "dev.mysql.com",
    "mariadb.com",
    "postgresql.org",
    "oracle.com",
    "nodejs.org",
    "spring.io",
    "golang.org",
    "rust-lang.org",
    "ruby-lang.org",
    "rubyonrails.org",
    "laravel.com",
    "symfony.com",
    "wordpress.org",
    "drupal.org",
    "react.dev",
    "angular.io",
    "vuejs.org",
    "svelte.dev",
    "nextjs.org",
    "nuxt.com",
])


def _is_authoritative_url(url: str) -> bool:
    """Return True when ``url`` appears to come from an authoritative source."""
    cleaned = url.split("#")[0].rstrip("/")
    for host in _AUTHORITATIVE_HOSTS:
        if host in cleaned:
            return True
    lower = cleaned.lower()
    if any(p in lower for p in (
        "/docs/",
        "/migration",
        "/migration/",
        "/release-notes",
        "/releases",
        "/changelog",
        "/announcements",
    )):
        return True
    return False


def _classify_source(result: SearchResult) -> str:
    """Return 'authoritative' or 'non-authoritative' for a search result."""
    if _is_authoritative_url(result.url):
        return "authoritative"
    title = result.title.lower()
    if any(p in title for p in (
        "migration guide",
        "release notes",
        "changelog",
        "official documentation",
        "deprecation",
    )):
        lower_url = result.url.lower()
        if not any(blog in lower_url for blog in (
            "medium.com",
            "dev.to",
            "blogspot",
            "wordpress.com",
            "tumblr",
        )):
            return "authoritative"
    return "non-authoritative"


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------


def _short_version(version: str) -> str:
    """Trim a version to ``major.minor`` ('3.2.0' -> '3.2', '4' -> '4').

    Search engines match official docs far better on "django 3.2 to 4.0"
    than on fully-pinned semver strings, whose results drift to unrelated
    projects' release notes.
    """
    parts = re.findall(r"[0-9]+", version.strip())
    if not parts:
        return version.strip()
    return ".".join(parts[:2])


def _build_queries(technology: str, source_version: str | None, target_version: str) -> list[str]:
    """Ordered candidate search queries, most specific first.

    Short, focused queries work far better with real search engines than
    long OR-bagged ones; release-notes phrasing reliably surfaces the
    official version-to-version documentation.  Versions are searched as
    ``major.minor`` (see :func:`_short_version`).
    """
    tech = technology.strip().lower()
    source = _short_version(source_version) if source_version else None
    target = _short_version(target_version)
    queries: list[str] = []
    if source:
        queries.append(f"{tech} {source} to {target} release notes")
    queries.append(f"{tech} {target} release notes")
    if source:
        queries.append(f"{tech} {source} to {target} upgrade")
    else:
        queries.append(f"{tech} {target} upgrade")
    return queries


def _build_query(technology: str, source_version: str | None, target_version: str) -> str:
    """Primary search query targeting authoritative migration documentation."""
    return _build_queries(technology, source_version, target_version)[0]


# ---------------------------------------------------------------------------
# Page inspection – extract evidence from a retrieved page
# ---------------------------------------------------------------------------


# Generic documentation words that are never API identifiers. Prevents
# heading-style phrases ("Features removed in 4.0") and connector words
# ("The ... setting/class/method was removed") from becoming changes.
_GENERIC_WORDS = frozenset({
    "the", "a", "an", "this", "that", "these", "those", "it", "its",
    "is", "was", "are", "were", "be", "been", "has", "have", "had",
    "and", "or", "with", "from", "into", "instead", "favor", "renamed",
    "removed", "deprecated", "use", "used", "using", "now", "new", "old",
    "in", "of", "to", "as", "by", "on", "for", "not", "no", "version",
    "release", "feature", "features", "change", "changes", "support",
    "method", "function", "class", "parameter", "argument", "attribute",
    "option", "setting", "field", "value", "property", "module", "code",
    "api", "apis", "interface", "interfaces",
})

# Markdown inline-code spans (never trust raw regex over prose directly).
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
# Code-like identifiers for plain-text pages without backticks.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:[.\[\]()][A-Za-z0-9_.()\[\]-]*)*")
# Explicit old -> new notation.
_ARROW_RE = re.compile(r"([\w.\-]+)\s*->\s*([\w.\-]+)")


def _iter_body_sentences(content: str) -> "Iterator[tuple[str, str, str]]":
    """Yield ``(section, line, sentence)`` for each sentence in body text.

    Markdown heading lines are never yielded as sentences; instead they
    update the current section, which is recorded as evidence for the
    sentences that follow them.
    """
    section = "Migration changes"
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            heading = re.sub(r"[#*_`]+", " ", stripped).strip()
            if heading:
                section = heading[:100]
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", stripped):
            sentence = sentence.strip()
            if sentence:
                yield section, stripped, sentence


def _classify_sentence(sentence: str) -> "tuple[ChangeType, int, int] | None":
    """Map a sentence onto ``(change_type, old_index, new_index)``.

    Indices refer to positions in the sentence's code tokens; ``-1`` means
    the successor API is not stated. Rules are ordered from most to least
    specific, so e.g. "deprecated in favor of X" wins over plain
    "deprecated".
    """
    lowered = sentence.lower()
    if "in favor of" in lowered:
        return ChangeType.DEPRECATION, 0, 1
    if "renamed" in lowered and re.search(r"\b(?:to|into|as)\b", lowered):
        return ChangeType.REPLACEMENT, 0, 1
    if "instead of" in lowered:
        # "Use X instead of Y" - Y is the API being replaced.
        return ChangeType.REPLACEMENT, 1, 0
    if "replaced by" in lowered:
        return ChangeType.REPLACEMENT, 0, 1
    if re.search(r"\breplace\b", lowered) and re.search(r"\bwith\b", lowered):
        return ChangeType.REPLACEMENT, 0, 1
    if "changed to" in lowered:
        return ChangeType.REPLACEMENT, 0, 1
    # Removal/deprecation are checked before the vaguer "is now" pattern so
    # that e.g. "X is now deprecated" classifies as a deprecation, not a
    # replacement with an unknown successor.
    if re.search(r"\bremoved\b", lowered):
        return ChangeType.REMOVAL, 0, -1
    if re.search(r"\bdeprecated\b", lowered):
        return ChangeType.DEPRECATION, 0, -1
    if re.search(r"\bis now\b", lowered):
        return ChangeType.REPLACEMENT, 0, 1
    return None


def _release_note_versions(url: str) -> list[str]:
    """Version segments in a URL's ``/releases/<version>/`` path parts."""
    return re.findall(r"/releases/([\w.\-]+)/", url.lower() + "/")


def _version_segments(version: str) -> set[str]:
    """Comparable prefixes of a version string, e.g. ``4.0.0`` -> ``{4, 4.0, 4.0.0}``."""
    parts = re.findall(r"\d+", version or "")
    return {".".join(parts[:size]) for size in (1, 2, 3) if len(parts) >= size}


def _score_result(result: SearchResult, target_version: str | None = None) -> int:
    """Score a search result: lower is better (authoritative first).

    With ``target_version`` given, official pages whose URL points at the
    *target* version's release notes are boosted, other versions'
    release notes and generic API-reference pages are demoted.
    """
    classification = _classify_source(result)
    score = 0 if classification == "authoritative" else 1000
    title_lower = result.title.lower()
    snippet_lower = result.snippet.lower()
    if "migration" in title_lower:
        score -= 50
    if "release note" in title_lower or "release note" in snippet_lower:
        score -= 30
    if "changelog" in title_lower:
        score -= 30
    if target_version:
        wanted = _version_segments(target_version)
        for segment in _release_note_versions(result.url):
            if segment in wanted:
                score -= 40  # release notes for exactly the target version
            else:
                score += 20  # some other version's release notes
        if "/ref/" in result.url.lower():
            score += 15  # API reference ranks below guides/release notes
    return score


def _select_best_sources(
    results: list[SearchResult], limit: int = 5, target_version: str | None = None
) -> list[SearchResult]:
    """Select the best (most authoritative, most relevant) results."""
    scored = [(_score_result(r, target_version), r) for r in results]
    scored.sort(key=lambda x: x[0])
    selected = []
    seen_urls: set[str] = set()
    for _score, r in scored:
        url = r.url.split("#")[0].rstrip("/")
        if url in seen_urls:
            continue
        seen_urls.add(url)
        selected.append(r)
        if len(selected) >= limit:
            break
    return selected


# ---------------------------------------------------------------------------
# Knowledge extraction from a page
# ---------------------------------------------------------------------------


def _looks_like_code(token: str) -> bool:
    """Heuristic: does ``token`` look like code rather than prose?

    Trailing closing punctuation (``)``, quotes) is ignored so that
    prose asides like ``(elided)`` do not pass the test, while real
    call-like tokens such as ``Model.dict()`` still do.
    """
    stripped = token.rstrip(".,;:)'\"")
    return (
        any(ch in stripped for ch in "._()[]")
        or any(ch.isupper() for ch in stripped)
    )


def _code_tokens(sentence: str) -> list[str]:
    """Code identifiers in order of appearance.

    Backticked spans are preferred; for plain-text pages the fallback
    extracts code-like identifiers and drops generic prose words.
    """
    tokens = [t.strip() for t in _BACKTICK_RE.findall(sentence)]
    # Drop empty spans and prose captured between `` pairs; real code spans
    # are single identifiers (may contain dots/parens but not spaces).
    tokens = [t for t in tokens if t and " " not in t]
    if tokens:
        return tokens
    fallback: list[str] = []
    for token in _IDENT_RE.findall(sentence):
        if token.lower() in _GENERIC_WORDS:
            continue
        if not _looks_like_code(token):
            continue
        fallback.append(token)
    return fallback


def _clean_token(token: str | None) -> str | None:
    """Trim whitespace, stray backticks and trailing punctuation."""
    if token is None:
        return None
    token = token.strip().strip("`").strip()
    token = token.rstrip(".,;:")
    return token or None


def _plausible_identifier(token: str | None) -> bool:
    """Reject empty/generic subjects so no junk changes are fabricated."""
    if not token or len(token) < 3:
        return False
    # Identifiers never start with punctuation; a leading paren/quote
    # means the "token" is a prose aside such as "(elided)".
    if not (token[0].isalnum() or token[0] == "_"):
        return False
    return token.lower() not in _GENERIC_WORDS


def _extract_changes_from_page(
    spec: MigrationSpec,
    page: PageContent,
    source_title: str,
) -> list[MigrationChange]:
    """Extract MigrationChange objects from an already-retrieved page.

    Search snippets are never trusted: extraction works sentence by sentence
    over the *retrieved page body*. Code identifiers are taken from
    backticked spans first, with a code-like identifier fallback for
    plain-text pages. Every change carries evidence pointing at the exact
    source location (page title, section heading, verbatim sentence, URL).
    Sentences without a recognizable migration statement produce no change -
    the agent never invents one.
    """
    changes: list[MigrationChange] = []
    seen: set[tuple] = set()

    for section, line, sentence in _iter_body_sentences(page.content):
        classified = _classify_sentence(sentence)
        if classified is not None:
            change_type, old_idx, new_idx = classified
            tokens = _code_tokens(sentence)
            raw_old = tokens[old_idx] if 0 <= old_idx < len(tokens) else None
            raw_new = tokens[new_idx] if 0 <= new_idx < len(tokens) else None
            # A bare "removed"/"deprecated" statement only counts when its
            # subject appears *before* the keyword ("`X` was removed").
            # Otherwise the sentence merely mentions removal ("...may need
            # to be removed manually before running `RemoveField`") and the
            # code token is not the removed API -- do not fabricate a change.
            if new_idx == -1 and raw_old is not None:
                keyword = "removed" if change_type == ChangeType.REMOVAL else "deprecated"
                lowered = sentence.lower()
                subject_pos = lowered.find(raw_old.lower())
                keyword_pos = lowered.find(keyword)
                if subject_pos < 0 or keyword_pos < 0 or subject_pos >= keyword_pos:
                    continue
            old = raw_old
            new = raw_new
        else:
            arrow = _ARROW_RE.search(sentence)
            if arrow is None:
                continue  # No recognizable migration statement - skip.
            change_type = ChangeType.CONFIGURATION
            old, new = arrow.group(1), arrow.group(2)

        old = _clean_token(old)
        new = _clean_token(new)
        if not _plausible_identifier(old):
            continue
        if new is not None:
            if not _plausible_identifier(new):
                continue
            if old.lower() == new.lower():
                continue
        if change_type == ChangeType.REPLACEMENT and new is None:
            # A replacement without a stated successor is not verifiable
            # ("X was replaced by None" would be fabricated) - skip it.
            continue

        if change_type == ChangeType.REPLACEMENT:
            description = f"{old} was replaced by {new} in the target version."
        elif change_type == ChangeType.REMOVAL:
            description = f"{old} was removed in the target version."
        elif change_type == ChangeType.DEPRECATION:
            description = f"{old} is deprecated in the target version."
        else:
            description = f"Configuration {old} changed to {new}."

        key = (change_type, old, new)
        if key in seen:
            continue
        seen.add(key)

        changes.append(
            MigrationChange(
                change_type=change_type,
                old=old,
                new=new,
                description=description,
                evidence=Evidence(
                    source=page.title or source_title,
                    section=section or "Migration changes",
                    excerpt=sentence if len(sentence) >= 20 else line,
                    url=page.url,
                ),
            )
        )

    return changes


# ---------------------------------------------------------------------------
# Main acquisition function for dynamic knowledge
# ---------------------------------------------------------------------------


def acquire_migration_knowledge(spec: MigrationSpec) -> "KnowledgeAcquisition":
    """Acquire migration knowledge for ``spec`` from authoritative web sources.

    This function:
    1. Searches for authoritative migration documentation
    2. Selects the best results (preferring official sources)
    3. Retrieves and inspects the source pages
    4. Extracts MigrationChange objects with evidence
    5. Returns a KnowledgeAcquisition result

    If no authoritative migration information can be found or verified,
    returns an unsupported result with an explicit reason.
    """
    technology = spec.technology.strip().lower()
    if not technology:
        return _unsupported(spec, "No technology was specified in the migration spec.")

    from ..knowledge import _REGISTRY, _major_of
    source_major = _major_of(spec.source_version)
    target_major = _major_of(spec.target_version)

    if target_major is None:
        return _unsupported(
            spec,
            f"Unrecognized target version {spec.target_version!r}; "
            "cannot select a knowledge source.",
        )

    static_source = _REGISTRY.get((technology, source_major, target_major))
    if static_source is not None:
        from ..knowledge import KnowledgeAcquisition
        return KnowledgeAcquisition(spec=spec, supported=True, changes=list(static_source.changes))

    backend = _default_backend()
    results: list[SearchResult] = []
    for query in _build_queries(technology, spec.source_version, spec.target_version):
        results = backend.search(query, prefer_authoritative=True)
        if results:
            break

    if not results:
        return _unsupported(
            spec,
            f"No search results found for {technology} migration from "
            f"{spec.source_version or 'unknown'} to {spec.target_version}.",
        )

    selected = _select_best_sources(results, limit=5, target_version=spec.target_version)
    changes: list[MigrationChange] = []
    authoritative_found = False

    for result in selected:
        is_auth = _classify_source(result) == "authoritative"
        if is_auth:
            authoritative_found = True

        page = backend.fetch_page(result.url)
        if page is None:
            continue

        page_changes = _extract_changes_from_page(spec, page, result.title)
        changes.extend(page_changes)

        if is_auth and page_changes:
            break

    seen: set[tuple] = set()
    unique_changes: list[MigrationChange] = []
    for change in changes:
        key = (change.change_type, change.old, change.new)
        if key not in seen:
            seen.add(key)
            unique_changes.append(change)

    if not unique_changes:
        if not authoritative_found:
            return _unsupported(
                spec,
                f"No authoritative migration documentation found for {technology} "
                f"{spec.source_version or 'unknown'} -> {spec.target_version}.",
            )
        return _unsupported(
            spec,
            f"Could not extract verifiable migration changes from the available "
            f"authoritative sources for {technology} {spec.source_version or 'unknown'} -> {spec.target_version}.",
        )

    from ..knowledge import KnowledgeAcquisition
    return KnowledgeAcquisition(spec=spec, supported=True, changes=unique_changes)


def _unsupported(spec: MigrationSpec, reason: str) -> "KnowledgeAcquisition":
    """Return an unsupported knowledge acquisition result."""
    from ..knowledge import KnowledgeAcquisition
    return KnowledgeAcquisition(spec=spec, supported=False, reason=reason)
