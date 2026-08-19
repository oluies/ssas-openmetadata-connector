"""[MS-CSDLBI] parser for DISCOVER_CSDL_METADATA (tabular models).

An EntityType is a table; an EDM Property (with a Type) is a column; the paired
BI-annotation Property marks system columns (Contents="RowNumber", skipped) and
measures (contains a <Measure>). An Association is a table relationship.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .enums import edm_to_om_type


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(el: ET.Element, name: str, default: str = "") -> str:
    """Get an attribute by local name, ignoring any namespace prefix (BI annotations)."""
    for key, val in el.attrib.items():
        if _local(key) == name:
            return val
    return default


@dataclass(frozen=True)
class Column:
    name: str
    edm_type: str
    om_type: str
    nullable: bool
    is_measure: bool = False


@dataclass
class Table:
    name: str
    columns: list[Column] = field(default_factory=list)

    @property
    def measures(self) -> list[Column]:
        return [c for c in self.columns if c.is_measure]


@dataclass(frozen=True)
class Relationship:
    from_table: str   # the many-side (foreign key)
    to_table: str     # the one-side (primary key)


@dataclass
class Model:
    tables: list[Table] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)


def _parse_entity_type(et_el: ET.Element) -> Table:
    table = Table(name=et_el.attrib.get("Name", ""))
    for child in list(et_el):
        # EDM column properties are direct children with a Type attribute.
        if _local(child.tag) != "Property" or "Type" not in child.attrib:
            continue
        # The BI annotation is nested INSIDE the EDM Property: a bi:Property carrying
        # Contents (e.g. "RowNumber" = system column) or a bi:Measure element.
        is_system = any(
            _local(a.tag) == "Property" and _attr(a, "Contents") == "RowNumber"
            for a in child
        )
        if is_system:
            continue
        is_measure = any(_local(a.tag) == "Measure" for a in child)
        edm = child.attrib.get("Type", "")
        table.columns.append(
            Column(
                name=child.attrib.get("Name", ""),
                edm_type=edm,
                om_type=edm_to_om_type(edm),
                nullable=child.attrib.get("Nullable", "true") != "false",
                is_measure=is_measure,
            )
        )
    return table


def _strip_ns_prefix(type_ref: str) -> str:
    return type_ref.rsplit(".", 1)[-1]


def _parse_association(assoc_el: ET.Element) -> Relationship | None:
    ends = [c for c in list(assoc_el) if _local(c.tag) == "End"]
    if len(ends) != 2:
        return None
    many = one = None
    for end in ends:
        table = _strip_ns_prefix(end.attrib.get("Type", ""))
        if end.attrib.get("Multiplicity") == "*":
            many = table
        else:
            one = table
    if many and one:
        return Relationship(from_table=many, to_table=one)
    return None


def parse_csdl(text: str) -> Model:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return Model()
    model = Model()
    for el in root.iter():
        ln = _local(el.tag)
        if ln == "EntityType" and el.attrib.get("Name"):
            model.tables.append(_parse_entity_type(el))
        elif ln == "Association" and el.attrib.get("Name"):
            rel = _parse_association(el)
            if rel:
                model.relationships.append(rel)
    return model
