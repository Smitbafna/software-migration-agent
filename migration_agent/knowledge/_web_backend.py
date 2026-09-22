"""Real web search and page retrieval backend -- standard library only.

Search queries the DuckDuckGo *Lite* HTML endpoint via POST (no API key,
no third-party dependencies).  When that endpoint serves a bot-check page
instead of results (it rate-limits and distrusts plain-urllib clients
from time to time), the backend falls back to Bing's machine readable
RSS output (``format=rss``, parsed with ``xml.etree``).
Pages are retrieved with ``urllib.request``; the final URL -- after
following any redirects -- is preserved on the returned ``PageContent``
and therefore in evidence URLs.

Snippets from the search endpoint are informational and used only for
ranking; they are never used as evidence.  Every ``MigrationChange`` is
extracted by the acquisition pipeline from the body of a page actually
retrieved through :meth:`WebSearchBackend.fetch_page`.

The HTML-to-text conversion renders real-world pages into the
conventions the acquisition extractor understands:

* ``<h1>``..``<h6>`` headings become ``## heading`` lines (sections);
* inline ``<code>``/``<tt>`` spans become `` `code` `` backtick tokens;
* ``<pre>`` blocks become single-line backticked entries.
"""

from __future__ import annotations

import html as _html
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .acquisition import PageContent, SearchBackend, SearchResult, _classify_source

_SEARCH_ENDPOINT = "https://lite.duckduckgo.com/lite/"
_BING_ENDPOINT = "https://www.bing.com/search"
_REQUEST_TIMEOUT_SECONDS = 15.0
_MAX_PAGE_BYTES = 2_000_000
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) migration-agent/1.0 "
    "(dynamic-migration-knowledge; stdlib-urllib)"
)


@dataclass(frozen=True)
class _SearchResult:
    """Concrete :class:`SearchResult` (title/url/snippet, structural match)."""

    title: str
    url: str
    snippet: str


@dataclass(frozen=True)
class _PageContent:
    """Concrete :class:`PageContent` (url/title/content, structural match)."""

    url: str
    title: str
    content: str


def _http_get(
    url: str,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """GET (or POST when ``data`` is given) ``url``.

    Returns ``(final_url, content_type, body_text)``.  Redirects are
    followed automatically by urllib; ``final_url`` is the URL of the
    resource actually retrieved.  Raises on HTTP/network errors (callers
    translate that into ``None``/empty results).
    """
    request_headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
    )
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
        final_url = response.geturl() or url
        content_type = (response.headers.get_content_type() or "").lower()
        charset = response.headers.get_content_charset()
        raw = response.read(_MAX_PAGE_BYTES)
    return final_url, content_type, _decode_body(raw, charset)


def _http_post(url: str, data: bytes) -> tuple[str, str, str]:
    """POST ``data`` to ``url``; same return contract as :func:`_http_get`."""
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": _SEARCH_ENDPOINT,
        },
    )
    with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
        final_url = response.geturl() or url
        content_type = (response.headers.get_content_type() or "").lower()
        charset = response.headers.get_content_charset()
        raw = response.read(_MAX_PAGE_BYTES)
    return final_url, content_type, _decode_body(raw, charset)


def _decode_body(raw: bytes, header_charset: str | None) -> str:
    """Decode ``raw`` using the best available charset information."""
    candidates: list[str] = []
    if header_charset:
        candidates.append(header_charset)
    meta_match = re.search(rb"""charset=["']?([\w-]+)""", raw[:4096])
    if meta_match:
        candidates.append(meta_match.group(1).decode("ascii", "ignore"))
    candidates += ["utf-8", "cp1252", "latin-1"]
    tried: set[str] = set()
    for encoding in candidates:
        encoding = encoding.strip().lower()
        if not encoding or encoding in tried:
            continue
        tried.add(encoding)
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Search-side parsing (DuckDuckGo Lite HTML)
# ---------------------------------------------------------------------------

_A_TAG_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))"""
)
_SNIPPET_RE = re.compile(
    r"""<td[^>]*class=['"]result-snippet['"][^>]*>(.*?)</td>""",
    re.IGNORECASE | re.DOTALL,
)

_BOT_PAGE_MARKERS = (
    "anomaly",
    "unfortunately, bots use duckduckgo too",
    "if this error persists",
    "captcha",
)


def _is_bot_check_page(page_html: str) -> bool:
    """Detect a search-engine anti-bot/challenge page (no real results)."""
    lowered = page_html.lower()
    if "result-link" in lowered:
        return False  # real results page
    return any(marker in lowered for marker in _BOT_PAGE_MARKERS)


def _parse_bing_rss(body: str) -> list[_SearchResult]:
    """Parse Bing's ``format=rss`` output into search results."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    items = root.findall(".//channel/item") or root.findall(".//item")
    results: list[_SearchResult] = []
    for item in items:
        title = _clean_text(item.findtext("title") or "")
        url = (item.findtext("link") or "").strip()
        snippet = _clean_text(item.findtext("description") or "")[:400]
        if url.startswith(("http://", "https://")) and title:
            results.append(_SearchResult(title=title, url=url, snippet=snippet))
    return results


def _tag_attrs(tag: str) -> dict[str, str]:
    """Extract attribute name/value pairs from a raw HTML tag string."""
    attrs: dict[str, str] = {}
    for match in _ATTR_RE.finditer(tag):
        value = next(group for group in match.groups()[1:] if group is not None)
        attrs[match.group(1).lower()] = _html.unescape(value)
    return attrs


def _clean_text(fragment: str) -> str:
    """Strip tags from an HTML fragment and collapse whitespace."""
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _decode_redirect(href: str) -> str | None:
    """Resolve a DuckDuckGo redirect URL to the real target URL.

    Lite result links look like ``//duckduckgo.com/l/?uddg=<encoded>&rut=...``.
    Plain http(s) URLs pass through unchanged; anything else (relative
    pagination links, protocol-less junk) is rejected.
    """
    href = _html.unescape((href or "").strip())
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urllib.parse.urlsplit(href)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc.lower().endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        targets = urllib.parse.parse_qs(parsed.query).get("uddg")
        if not targets:
            return None
        target = urllib.parse.unquote(targets[0])
        try:
            target_parsed = urllib.parse.urlsplit(target)
        except ValueError:
            return None
        if target_parsed.scheme in ("http", "https"):
            return target
        return None
    return href


def _parse_lite_results(page_html: str) -> list[_SearchResult]:
    """Parse a DuckDuckGo Lite results page into search results."""
    snippets = [_clean_text(m.group(1))[:400] for m in _SNIPPET_RE.finditer(page_html)]

    entries: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for match in _A_TAG_RE.finditer(page_html):
        attrs = _tag_attrs(match.group(1))
        if "result-link" not in attrs.get("class", "").split():
            continue
        url = _decode_redirect(attrs.get("href", ""))
        title = _clean_text(match.group(2))
        if not url or not title or url in seen_urls:
            continue
        seen_urls.add(url)
        entries.append((title, url))

    return [
        _SearchResult(
            title=title,
            url=url,
            snippet=snippets[index] if index < len(snippets) else "",
        )
        for index, (title, url) in enumerate(entries)
    ]


def _extract_title(page_html: str) -> str:
    """Best-effort page title from ``<title>`` or the og:title meta tag."""
    match = re.search(r"<title\b[^>]*>(.*?)</title>", page_html, re.IGNORECASE | re.DOTALL)
    if match:
        title = _clean_text(match.group(1))
        if title:
            return title
    match = re.search(r"""<meta[^>]+(?:property|name)=['"]og:title['"][^>]*>""", page_html, re.IGNORECASE)
    if match:
        title = _clean_text(_tag_attrs(match.group(0)).get("content", ""))
        if title:
            return title
    return ""


# ---------------------------------------------------------------------------
# HTML -> text conversion (renders pages into extractor conventions)
# ---------------------------------------------------------------------------

_DROP_BLOCK_RE = re.compile(
    r"(?is)<(script|style|noscript|template|svg|iframe|head|form|button|select|option)\b.*?</\1\s*>"
)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_PRE_RE = re.compile(r"(?is)<pre\b[^>]*>(.*?)</pre>")
_CODE_RE = re.compile(r"(?is)<(?:code|tt)\b[^>]*>(.*?)</(?:code|tt)>")
_HEADING_RE = re.compile(r"(?is)<h[1-6]\b[^>]*>(.*?)</h[1-6]>")
_BREAK_RE = re.compile(r"(?i)<br\s*/?>|<hr\s*/?>")
_BLOCK_TAG_RE = re.compile(
    r"(?i)</?(?:p|div|li|ul|ol|tr|table|thead|tbody|section|article|header|footer|"
    r"nav|main|blockquote|dl|dt|dd|figure|figcaption|details|summary|h[1-6]|pre|title)\b[^>]*>"
)
_TAG_RE = re.compile(r"<[^>]+>")


def _render_pre_block(inner: str) -> str:
    """Render a ``<pre>`` block as one backticked entry per source line."""
    text = _TAG_RE.sub(" ", inner)
    text = _html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(f"`{line}`" for line in lines if line)


def _html_to_text(page_html: str) -> str:
    """Convert an HTML page into plain text the extractor can work with.

    Headings become ``## heading`` lines (they turn into evidence
    sections), inline code spans and ``<pre>`` lines become backticked
    tokens (the extractor's highest-priority code source), and block
    tags become line breaks so sentence boundaries survive conversion.
    """
    text = _DROP_BLOCK_RE.sub(" ", page_html)
    text = _COMMENT_RE.sub(" ", text)
    text = _PRE_RE.sub(lambda m: "\n" + _render_pre_block(m.group(1)) + "\n", text)
    text = _CODE_RE.sub(lambda m: f" `{_clean_text(m.group(1))}` ", text)
    text = _HEADING_RE.sub(lambda m: "\n## " + _clean_text(m.group(1)) + "\n", text)
    text = _BREAK_RE.sub("\n", text)
    text = _BLOCK_TAG_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(text)
    text = text.replace("\r", "")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# The backend
# ---------------------------------------------------------------------------


class WebSearchBackend(SearchBackend):
    """Live ``SearchBackend``: DuckDuckGo Lite (POST) with a Bing RSS
    fallback, plus urllib page fetches.

    Search snippets are returned for display/ranking only -- the
    acquisition pipeline never treats them as evidence, because every
    change is extracted from a page body retrieved by :meth:`fetch_page`.
    A per-instance cache keeps repeated identical queries off the wire.
    """

    def __init__(self) -> None:
        self._search_cache: dict[tuple[str, bool], tuple[_SearchResult, ...]] = {}
        self._ddg_ok = True  # flipped off after a bot-check page

    def search(self, query: str, prefer_authoritative: bool = True) -> list[SearchResult]:
        """Search the web; rank official documentation first when asked."""
        query = (query or "").strip()
        if not query:
            return []
        cache_key = (query, prefer_authoritative)
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return list(cached)

        results = self._search_ddg(query) if self._ddg_ok else []
        if not results:
            # DuckDuckGo serves a bot-check page instead of results when it
            # rate-limits or distrusts the client; retry via Bing RSS.
            results = self._search_bing(query)
        if prefer_authoritative:
            # Stable sort: official sources first, engine order otherwise.
            results.sort(
                key=lambda result: 0 if _classify_source(result) == "authoritative" else 1
            )
        self._search_cache[cache_key] = tuple(results)
        return list(results)

    def _search_ddg(self, query: str) -> list[_SearchResult]:
        """Search DuckDuckGo Lite (POST form submission)."""
        data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        try:
            _, _, page_html = _http_post(_SEARCH_ENDPOINT, data)
        except (urllib.error.URLError, OSError, ValueError):
            return []
        if _is_bot_check_page(page_html):
            self._ddg_ok = False
            return []
        return _parse_lite_results(page_html)

    def _search_bing(self, query: str) -> list[_SearchResult]:
        """Search Bing's machine readable RSS output."""
        url = _BING_ENDPOINT + "?" + urllib.parse.urlencode({"q": query, "format": "rss"})
        try:
            _, _, body = _http_get(url)
        except (urllib.error.URLError, OSError, ValueError):
            return []
        return _parse_bing_rss(body)

    def fetch_page(self, url: str) -> _PageContent | None:
        """Retrieve a page body, preserving the final (post-redirect) URL."""
        url = (url or "").strip()
        if not re.match(r"(?i)^https?://", url):
            return None
        try:
            final_url, content_type, page_html = _http_get(url)
        except (urllib.error.URLError, OSError, ValueError):
            return None
        if content_type and not content_type.startswith(
            ("text/", "application/xhtml", "application/xml")
        ):
            return None
        text = _html_to_text(page_html)
        if len(text) < 200:
            # Page did not yield a meaningful body -- refuse to guess.
            return None
        title = _extract_title(page_html)
        return _PageContent(url=final_url or url, title=title or url, content=text)


