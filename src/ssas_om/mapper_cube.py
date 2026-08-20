"""MDSCHEMA cube -> OpenMetadata Dashboard DataModel ingestion plan (T011).

A multidimensional cube maps to a Database service (option B): the cube is a schema,
its dimensions become tables of attribute columns, and a synthetic Measures table holds
the visible measures. This reuses the tabular database emission path cleanly, avoiding
OpenMetadata's DashboardDataModel requirement for a vendor-specific dataModelType that
does not represent an SSAS cube. See docs/discovery-report.md.
"""
from __future__ import annotations

from . import mdschema
from .plan import ColumnPlan, SchemaPlan, ServicePlan, TablePlan


def cube_schema(cube: mdschema.Cube) -> SchemaPlan:
    """One cube -> one schema: dimensions + a synthetic Measures table."""
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
    return SchemaPlan(name=cube.name, tables=tables)


def plan_cube(cube: mdschema.Cube, service: str, database: str) -> ServicePlan:
    return ServicePlan(service=service, service_type="database",
                       database=database, schemas=[cube_schema(cube)])


def plan_cubes(cubes: list[mdschema.Cube], service: str, database: str) -> ServicePlan:
    return ServicePlan(service=service, service_type="database", database=database,
                       schemas=[cube_schema(c) for c in cubes])
