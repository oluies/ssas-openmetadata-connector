"""SDK-free ingestion plan — the shape the connector will emit into OpenMetadata.

Keeping the plan independent of the OpenMetadata SDK lets the mapping logic be unit
tested offline (constitution III); the Source turns a plan into SDK requests.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ColumnPlan:
    name: str
    data_type: str          # OpenMetadata DataType name (e.g. STRING, BIGINT, DECIMAL)
    is_measure: bool = False
    description: str | None = None


@dataclass
class TablePlan:
    name: str
    columns: list[ColumnPlan] = field(default_factory=list)


@dataclass
class SchemaPlan:
    name: str
    tables: list[TablePlan] = field(default_factory=list)


@dataclass
class ServicePlan:
    service: str            # OpenMetadata service name
    service_type: str       # "database" | "dashboard"
    database: str
    schemas: list[SchemaPlan] = field(default_factory=list)


@dataclass(frozen=True)
class RelationshipPlan:
    from_table: str
    to_table: str
