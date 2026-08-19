"""Prove the offline gate, and that fixtures carry no identifying tokens.

Checks use PATTERNS, never literal sensitive values, so this test never itself
embeds a host, IP or machine name.
"""
import re
import socket

import pytest
from pytest_socket import SocketBlockedError

# Patterns that must never appear in a committed fixture (constitution: no leaks).
LEAK_PATTERNS = {
    "ipv4": re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),
    "netbios": re.compile(r"\bWIN-[A-Z0-9]{6,}\b"),
    "sid": re.compile(r"\bS-1-(?:\d+-){1,}\d+\b"),
    "connstring": re.compile(r"(?i)\b(Data Source|Initial Catalog|User ID|Password)="),
}


def test_socket_is_blocked():
    with pytest.raises(SocketBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_fixture_loader_reads_response(fixture_xml):
    xml = fixture_xml("tab", "discover.DBSCHEMA_CATALOGS")
    assert "DiscoverResponse" in xml


def test_missing_fixture_raises(fixture_xml):
    with pytest.raises(FileNotFoundError):
        fixture_xml("tab", "does.not.exist")


def test_no_identifying_tokens_in_fixtures(fixtures_root):
    offenders = []
    for path in fixtures_root.rglob("*.xml"):
        text = path.read_text(encoding="utf-8")
        for name, pat in LEAK_PATTERNS.items():
            if pat.search(text):
                offenders.append(f"{path.name}: {name}")
    assert not offenders, f"identifying tokens found: {offenders}"
