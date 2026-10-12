"""CSDL tabular model -> OpenMetadata database-service ingestion plan (T010).

A tabular catalog becomes a database service; the model's tables become tables with
typed columns; measures are columns flagged as measures. Relationships are carried
through for table-level lineage inside the model.
"""

from __future__ import annotations

import re

from . import csdl
from .mdschema import MeasureDefinition
from .plan import ColumnPlan, RelationshipPlan, SchemaPlan, ServicePlan, TablePlan

SCHEMA_NAME = "Model"  # a tabular model exposes a single cube named "Model"


def _canonical(name: str) -> str:
    """A measure name with the identifier-safe spelling flattened out.

    MDSCHEMA returns the modeller's name ("Total Quantity"); CSDL's EDM property
    is identifier-safe ("Total_Quantity"). The BI annotation normally carries the
    first as ReferenceName, which is the join this code prefers -- but a model
    whose CSDL omits that annotation would match nothing at all, and the symptom
    is a description that reads "measure", indistinguishable from a server that
    reported no definition. Underscores and runs of whitespace collapse to one
    space, and case is folded.
    """
    return re.sub(r"[\s_]+", " ", name).strip().casefold()


def _find_definition(
    column: csdl.Column, definitions: dict[str, MeasureDefinition]
) -> MeasureDefinition | None:
    """The definition for one measure column, by the most exact key that matches.

    Reference name, then column name, then the canonical form -- and the last only
    when exactly ONE definition canonicalises to it. A model holding both
    "Gross Margin" and "Gross_Margin" would otherwise have them silently swapped,
    which is worse than the missing description this fallback exists to prevent.
    """
    for key in (column.reference_name, column.name):
        if key and key in definitions:
            return definitions[key]
    wanted = _canonical(column.reference_name or column.name)
    matches = [d for name, d in definitions.items() if _canonical(name) == wanted]
    return matches[0] if len(matches) == 1 else None


# Rendered above already, so repeating them under the raw block would just be
# noise -- everything else the server sent is reproduced verbatim.
_ALREADY_SHOWN = ("DESCRIPTION", "EXPRESSION")


def _rowset_block(definition: MeasureDefinition) -> str:
    """Everything else MDSCHEMA_MEASURES said about this measure, as it said it.

    The server returns about fifteen cells per measure and this connector acted on
    five of them, so the rest -- the unique name, the captions, the aggregator, the
    display folder, the format string, the data type, the SQL column name -- were
    read and thrown away. They are reproduced here, in the server's own order,
    under their own heading, so the catalog shows what the model actually says
    rather than this connector's selection from it.

    Markdown, because OpenMetadata renders a description as markdown: the keys are
    code-formatted so a reader can tell a rowset column from prose.
    """
    rows = [
        f"- `{name}`: {value}" for name, value in definition.fields if name not in _ALREADY_SHOWN
    ]
    if not rows:
        return ""
    return "**MDSCHEMA_MEASURES**\n" + "\n".join(rows)


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
    and joining on that matches nothing at all. Where the annotation is missing,
    `_find_definition` falls back to the canonical spelling.
    """
    if not column.is_measure:
        return None
    definition = _find_definition(column, definitions)
    if definition is None:
        return "measure"
    parts = [definition.description.strip()] if definition.description.strip() else []
    if definition.expression.strip():
        parts.append(f"Expression:\n{definition.expression.strip()}")
    rowset = _rowset_block(definition)
    if rowset:
        parts.append(rowset)
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
