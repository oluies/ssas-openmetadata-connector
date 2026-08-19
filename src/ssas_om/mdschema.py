"""MDSCHEMA rowset parser for multidimensional models ([MS-SSAS]).

Reader-accessible metadata: cube, measure groups, dimensions, measures, and the
attribute columns (from hierarchies/levels). Integer enums are mapped via `enums`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .client import XmlaClient, parse_rowset
from .enums import DIMENSION_TYPE, aggregator_name, oledb_to_om_type


@dataclass(frozen=True)
class MdMeasure:
    name: str
    measure_group: str
    aggregator: str
    visible: bool


@dataclass(frozen=True)
class MdColumn:
    name: str
    om_type: str


@dataclass
class MdDimension:
    name: str
    unique_name: str
    dtype: str
    columns: list[MdColumn] = field(default_factory=list)


@dataclass
class Cube:
    name: str
    measure_groups: list[str] = field(default_factory=list)
    dimensions: list[MdDimension] = field(default_factory=list)
    measures: list[MdMeasure] = field(default_factory=list)


def _cube_name(text: str) -> str:
    rows = parse_rowset(text)
    return rows[0].get("CUBE_NAME", "") if rows else ""


def parse_measures(text: str) -> list[MdMeasure]:
    out = []
    for r in parse_rowset(text):
        out.append(
            MdMeasure(
                name=r.get("MEASURE_NAME", ""),
                measure_group=r.get("MEASUREGROUP_NAME", ""),
                aggregator=aggregator_name(r.get("MEASURE_AGGREGATOR")),
                visible=r.get("MEASURE_IS_VISIBLE", "true") not in ("false", "0"),
            )
        )
    return out


def parse_dimensions(dims_text: str, levels_text: str) -> list[MdDimension]:
    # columns come from MDSCHEMA_LEVELS grouped by dimension, typed via LEVEL_DBTYPE
    cols_by_dim: dict[str, list[MdColumn]] = {}
    for r in parse_rowset(levels_text):
        dim = r.get("DIMENSION_UNIQUE_NAME", "")
        name = r.get("LEVEL_NAME", "")
        if not name or name == "(All)":
            continue
        cols_by_dim.setdefault(dim, []).append(
            MdColumn(name=name, om_type=oledb_to_om_type(r.get("LEVEL_DBTYPE")))
        )
    dims = []
    for r in parse_rowset(dims_text):
        uniq = r.get("DIMENSION_UNIQUE_NAME", "")
        dtype = DIMENSION_TYPE.get(int(r.get("DIMENSION_TYPE") or 0), "Unknown")
        dims.append(
            MdDimension(
                name=r.get("DIMENSION_NAME", ""),
                unique_name=uniq,
                dtype=dtype,
                columns=cols_by_dim.get(uniq, []),
            )
        )
    return dims


def build_cube(
    cubes_text: str, mg_text: str, dims_text: str, levels_text: str, measures_text: str
) -> Cube:
    return Cube(
        name=_cube_name(cubes_text),
        measure_groups=[r.get("MEASUREGROUP_NAME", "") for r in parse_rowset(mg_text)],
        dimensions=[d for d in parse_dimensions(dims_text, levels_text)
                    if d.dtype != "Measure"],
        measures=[m for m in parse_measures(measures_text) if m.visible],
    )


def build_cube_from_client(client: XmlaClient, catalog: str) -> Cube:
    def dmv(rowset: str) -> str:
        r = client.dmv(rowset, catalog=catalog)
        return r.text if r.ok else "<empty/>"

    return build_cube(
        dmv("MDSCHEMA_CUBES"), dmv("MDSCHEMA_MEASUREGROUPS"),
        dmv("MDSCHEMA_DIMENSIONS"), dmv("MDSCHEMA_LEVELS"), dmv("MDSCHEMA_MEASURES"),
    )
