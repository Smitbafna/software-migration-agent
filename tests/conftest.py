"""Shared pytest configuration.

Registers custom markers and auto-skips network-marked tests when the
machine has no outbound connectivity (or ``MIGRATION_AGENT_NET_TESTS=0``
is set), so the suite stays green in offline environments.
"""

import os
import socket

import pytest

_NETWORK_TARGET = ("lite.duckduckgo.com", 443)


def _network_available() -> bool:
    if os.environ.get("MIGRATION_AGENT_NET_TESTS") == "0":
        return False
    try:
        socket.create_connection(_NETWORK_TARGET, timeout=5).close()
        return True
    except OSError:
        return False


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "network: test requires outbound internet connectivity"
    )


def pytest_collection_modifyitems(config, items):
    if not any(item.get_closest_marker("network") for item in items):
        return
    if _network_available():
        return
    skip = pytest.mark.skip(reason="no outbound network connectivity")
    for item in items:
        if item.get_closest_marker("network"):
            item.add_marker(skip)
