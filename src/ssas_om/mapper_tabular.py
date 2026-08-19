"""CSDL tabular model -> OpenMetadata database-service ingestion plan (T010).

A tabular catalog becomes a database service; the model's tables become tables with
typed columns; measures are columns flagged as measures. Relationships are carried
through for table-level lineage inside the model.
"""
from __future__ import annotations

from . import csdl
from .plan import ColumnPlan, RelationshipPlan, SchemaPlan, ServicePlan, TablePlan

SCHEMA_NAME = "Model"  # a tabular model exposes a single cube named "Model"


def plan_tabular(
    model: csdl.Model, service: str, database: str
) -> tuple[ServicePlan, list[RelationshipPlan]]:
    tables: list[TablePlan] = []
    for t in model.tables:
        cols = [
            ColumnPlan(
                name=c.name,
                data_type=c.om_type,
                is_measure=c.is_measure,
                description="measure" if c.is_measure else None,
            )
            for c in t.columns
        ]
        tables.append(TablePlan(name=t.name, columns=cols))

    svc = ServicePlan(
        service=service,
        service_type="database",
        database=database,
        schemas=[SchemaPlan(name=SCHEMA_NAME, tables=tables)],
    )
    rels = [RelationshipPlan(r.from_table, r.to_table) for r in model.relationships]
    return svc, rels
