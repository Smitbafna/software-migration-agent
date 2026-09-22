"""Demo: dynamically acquire Django 3.2 -> 4.0 migration knowledge.

By default this uses the REAL web backend (DuckDuckGo Lite search +
stdlib page fetch), so results come from live official documentation.
Pass ``--mock`` to run against a deterministic fake backend instead
(useful offline).

In both modes a change is extracted from a *retrieved page* (never from
a search snippet), with full evidence attached.
"""

import sys
from dataclasses import dataclass

from migration_agent import MigrationSpec, acquire_migration_knowledge, set_backend


@dataclass
class R:
    title: str
    url: str
    snippet: str


@dataclass
class P:
    url: str
    title: str
    content: str


class DemoBackend:
    def search(self, query, prefer_authoritative=True):
        return [
            R(
                "Django 4.0 release notes",
                "https://docs.djangoproject.com/en/4.0/releases/4.0/",
                "Django 4.0 release notes (official).",
            )
        ]

    def fetch_page(self, url):
        # The agent fetches and inspects the page itself - snippet not trusted.
        return P(
            url,
            "Django 4.0 release notes",
            """
## Features removed in 4.0

The ``USE_L10N`` setting is deprecated in favor of ``USE_I18N``.
""",
        )


def main() -> int:
    if "--mock" in sys.argv[1:]:
        set_backend(DemoBackend())
        print("mode: mock backend (deterministic)")
    else:
        from migration_agent.knowledge._web_backend import WebSearchBackend

        set_backend(WebSearchBackend())
        print("mode: real web backend (DuckDuckGo Lite + urllib)")

    try:
        result = acquire_migration_knowledge(
            MigrationSpec(
                repository=".",
                technology="django",
                source_version="3.2.0",
                target_version="4.0.0",
            )
        )
    finally:
        set_backend(None)

    print("supported:", result.supported)
    print("reason:", result.reason)
    for change in result.changes:
        print(f"change: {change.change_type.value}: {change.old!r} -> {change.new!r}")
        print(f"  description: {change.description}")
        ev = change.evidence
        print(f"  evidence.source:   {ev.source}")
        print(f"  evidence.section:  {ev.section}")
        print(f"  evidence.excerpt:  {ev.excerpt[:200]!r}")
        print(f"  evidence.url:      {ev.url}")
    return 0 if result.supported else 1


if __name__ == "__main__":
    raise SystemExit(main())

