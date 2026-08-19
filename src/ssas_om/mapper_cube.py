"""MDSCHEMA cube -> OpenMetadata Dashboard DataModel ingestion plan (T011).

Per the clarify decision, a multidimensional cube maps to a Dashboard service with a
DashboardDataModel (measures + dimension attributes as its columns) — a cube-specific
shape distinct from the tabular database-service shape.
"""
from __future__ import annotations

from . import mdschema
from .plan import ColumnPlan, SchemaPlan, ServicePlan, TablePlan


def plan_cube(cube: mdschema.Cube, service: str, database: str) -> ServicePlan:
    # Each dimension becomes a "table" (data-model entity) of its attribute columns;
    # a synthetic Measures table holds the visible measures.
    tables: list[TablePlan] = []
    for dim in cube.dimensions:
        tables.append(
            TablePlan(
                name=dim.name,
                columns=[ColumnPlan(name=c.name, data_type=c.om_type) for c in dim.columns],
            )
        )
    if cube.measures:
        tables.append(
            TablePlan(
                name="Measures",
                columns=[
                    ColumnPlan(name=m.name, data_type="DECIMAL", is_measure=True,
                               description=f"{m.aggregator} of {m.measure_group}")
                    for m in cube.measures
                ],
            )
        )
    return ServicePlan(
        service=service,
        service_type="dashboard",
        database=database,
        schemas=[SchemaPlan(name=cube.name, tables=tables)],
    )
