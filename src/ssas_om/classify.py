"""Classify a catalog as tabular or multidimensional from DBSCHEMA_CATALOGS.

TYPE = 3 (tabular) / 0 (multidimensional). No admin-gated rowset is used.
Reference: [MS-SSAS] DBSCHEMA_CATALOGS.
"""
from __future__ import annotations

from dataclasses import dataclass

from .client import XmlaClient, parse_rowset
from .enums import catalog_kind


@dataclass(frozen=True)
class Catalog:
    name: str
    kind: str  # "tabular" | "multidimensional" | "unknown"
    compatibility_level: str | None = None


def catalogs_from_response(text: str) -> list[Catalog]:
    out: list[Catalog] = []
    for row in parse_rowset(text):
        name = row.get("CATALOG_NAME", "")
        if not name:
            continue
        out.append(
            Catalog(
                name=name,
                kind=catalog_kind(row.get("TYPE")),
                compatibility_level=row.get("COMPATIBILITY_LEVEL") or None,
            )
        )
    return out


def list_catalogs(client: XmlaClient) -> list[Catalog]:
    r = client.discover("DBSCHEMA_CATALOGS")
    if not r.ok:
        return []
    return catalogs_from_response(r.text)
