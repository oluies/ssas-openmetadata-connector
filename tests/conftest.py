"""Test harness: offline-first, fixture-driven.

Sockets are disabled globally via pytest addopts (`--disable-socket`); the tests here
prove the gate is active. A `fixture_xml` helper loads recorded, scrubbed XMLA responses
from tests/fixtures/xmla/<endpoint>/<name>.xml.
"""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "xmla"


@pytest.fixture
def fixture_xml():
    """Return a loader: fixture_xml('tab', 'discover.DBSCHEMA_CATALOGS') -> str."""
    def _load(endpoint: str, name: str) -> str:
        path = FIXTURES / endpoint / f"{name}.xml"
        if not path.exists():
            raise FileNotFoundError(f"no fixture: {path.relative_to(FIXTURES.parent.parent)}")
        return path.read_text(encoding="utf-8")

    return _load


@pytest.fixture
def fixtures_root() -> Path:
    return FIXTURES
