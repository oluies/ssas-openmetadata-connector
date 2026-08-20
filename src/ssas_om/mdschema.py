"""MDSCHEMA rowset parser for multidimensional models ([MS-SSAS]).

Reader-accessible metadata: cubes, measure groups, dimensions, measures, and the
attribute columns (from hierarchies/levels). Integer enums are mapped via `enums`.
A catalog may expose several cubes (and system perspectives), so rows are filtered
to real cubes and scoped by CUBE_NAME.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .client import XmlaClient, parse_rowset
from .enums import aggregator_name, dimension_type_name, oledb_to_om_type


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


def list_cube_names(cubes_text: str) -> list[str]:
    """Real cubes only: skip system perspectives ($-prefixed) and non-cube sources."""
    names: list[str] = []
    for r in parse_rowset(cubes_text):
        name = r.get("CUBE_NAME", "")
        # CUBE_SOURCE: 1 = CUBE (not a dimension/perspective source)
        source = r.get("CUBE_SOURCE", "1")
        if name and not name.startswith("$") and source in ("1", ""):
            names.append(name)
    return names


def _for_cube(rows: list[dict[str, str]], cube_name: str) -> list[dict[str, str]]:
    return [r for r in rows if r.get("CUBE_NAME", cube_name) == cube_name]


def parse_measures(text: str, cube_name: str) -> list[MdMeasure]:
    out = []
    for r in _for_cube(parse_rowset(text), cube_name):
        out.append(
            MdMeasure(
                name=r.get("MEASURE_NAME", ""),
                measure_group=r.get("MEASUREGROUP_NAME", ""),
                aggregator=aggregator_name(r.get("MEASURE_AGGREGATOR")),
                visible=r.get("MEASURE_IS_VISIBLE", "true") not in ("false", "0"),
            )
        )
    return out


def parse_dimensions(dims_text: str, levels_text: str, cube_name: str) -> list[MdDimension]:
    cols_by_dim: dict[str, list[MdColumn]] = {}
    for r in _for_cube(parse_rowset(levels_text), cube_name):
        dim = r.get("DIMENSION_UNIQUE_NAME", "")
        name = r.get("LEVEL_NAME", "")
        if not name or name == "(All)":
            continue
        cols_by_dim.setdefault(dim, []).append(
            MdColumn(name=name, om_type=oledb_to_om_type(r.get("LEVEL_DBTYPE")))
        )
    dims = []
    for r in _for_cube(parse_rowset(dims_text), cube_name):
        uniq = r.get("DIMENSION_UNIQUE_NAME", "")
        dims.append(
            MdDimension(
                name=r.get("DIMENSION_NAME", ""),
                unique_name=uniq,
                dtype=dimension_type_name(r.get("DIMENSION_TYPE")),
                columns=cols_by_dim.get(uniq, []),
            )
        )
    return dims


def build_cube(
    cube_name: str, mg_text: str, dims_text: str, levels_text: str, measures_text: str
) -> Cube:
    return Cube(
        name=cube_name,
        measure_groups=[
            r.get("MEASUREGROUP_NAME", "") for r in _for_cube(parse_rowset(mg_text), cube_name)
        ],
        dimensions=[d for d in parse_dimensions(dims_text, levels_text, cube_name)
                    if d.dtype != "Measure"],
        measures=[m for m in parse_measures(measures_text, cube_name) if m.visible],
    )


def build_cubes_from_client(client: XmlaClient, catalog: str) -> list[Cube]:
    def dmv(rowset: str) -> str:
        r = client.dmv(rowset, catalog=catalog)
        return r.text if r.ok else "<empty/>"

    cubes_text = dmv("MDSCHEMA_CUBES")
    mg, dims, levels, measures = (
        dmv("MDSCHEMA_MEASUREGROUPS"), dmv("MDSCHEMA_DIMENSIONS"),
        dmv("MDSCHEMA_LEVELS"), dmv("MDSCHEMA_MEASURES"),
    )
    return [build_cube(name, mg, dims, levels, measures)
            for name in list_cube_names(cubes_text)]
