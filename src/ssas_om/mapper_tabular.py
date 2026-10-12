"""CSDL tabular model -> OpenMetadata database-service ingestion plan (T010).

A tabular catalog becomes a database service; the model's tables become tables with
typed columns; measures are columns flagged as measures. Relationships are carried
through for table-level lineage inside the model.
"""
from __future__ import annotations

from . import csdl
from .mdschema import MeasureDefinition
from .plan import ColumnPlan, RelationshipPlan, SchemaPlan, ServicePlan, TablePlan

SCHEMA_NAME = "Model"  # a tabular model exposes a single cube named "Model"


def _measure_description(
    column: csdl.Column, definitions: dict[str, MeasureDefinition]
) -> str | None:
    """A measure's description: what the modeller wrote, plus the server's formula.

    The bare string "measure" was all a reader of the catalog got, while the model
    itself carries far more and gives it to a reader: MDSCHEMA_MEASURES.DESCRIPTION
    is free text the modeller authored -- in practice where the formula lives --
    and EXPRESSION is the server's own, populated for a calculated measure and
    empty for a plain aggregate.

    The join is on the measure's REFERENCE name, not the column name: CSDL makes
    the EDM property identifier-safe, so "Total Sales" arrives as "Total_Sales"
    and joining on it matches nothing at all.
    """
    if not column.is_measure:
        return None
    definition = definitions.get(column.reference_name or column.name)
    if definition is None:
        return "measure"
    parts = [definition.description.strip()] if definition.description.strip() else []
    if definition.expression.strip():
        parts.append(f"Expression:\n{definition.expression.strip()}")
    return "\n\n".join(parts) if parts else "measure"


def plan_tabular(
    model: csdl.Model,
    service: str,
    database: str,
    measure_definitions: dict[str, MeasureDefinition] | None = None,
) -> tuple[ServicePlan, list[RelationshipPlan]]:
    definitions = measure_definitions or {}
    tables: list[TablePlan] = []
    for t in model.tables:
        cols = [
            ColumnPlan(
                name=c.name,
                data_type=c.om_type,
                is_measure=c.is_measure,
                description=_measure_description(c, definitions),
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
