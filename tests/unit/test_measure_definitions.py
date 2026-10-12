"""Measure definitions from MDSCHEMA_MEASURES, joined onto the CSDL columns.

The rowset here is SYNTHESIZED to the shape a live instance returns, not recorded:
a real DESCRIPTION is free text a modeller wrote and can encode commercial rules
(docs/extracting-definitions.md says so under "What you still are disclosing"), so
committing one would disclose the model's semantics, not just its shape.

The CSDL side is the recorded response, because the join depends on a detail no
invented fixture would reproduce: CSDL makes the EDM property identifier-safe, so
the measure is the column `Total_Sales` while MDSCHEMA calls it `Total Sales`.
"""

from pathlib import Path

from ssas_om.csdl import parse_csdl
from ssas_om.mapper_tabular import plan_tabular
from ssas_om.mdschema import measure_definitions

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "xmla" / "tab"


def _rowset(rows: str) -> str:
    return (
        '<return><root xmlns="urn:schemas-microsoft-com:xml-analysis:rowset">'
        f"{rows}"
        "</root></return>"
    )


AGGREGATE = _rowset(
    "<row>"
    "<CATALOG_NAME>AWTabular</CATALOG_NAME><CUBE_NAME>Model</CUBE_NAME>"
    "<MEASURE_NAME>Total Sales</MEASURE_NAME>"
    "<DESCRIPTION>Business definition:\n"
    "Value of goods invoiced in the period.\n"
    "Technical definition:\n"
    "SUM(FactInternetSales[SalesAmount])</DESCRIPTION>"
    "<MEASURE_IS_VISIBLE>true</MEASURE_IS_VISIBLE>"
    "<MEASURE_DISPLAY_FOLDER>Sales</MEASURE_DISPLAY_FOLDER>"
    "<DEFAULT_FORMAT_STRING>#,0</DEFAULT_FORMAT_STRING>"
    "</row>"
)

CALCULATED = _rowset(
    "<row><MEASURE_NAME>Margin %</MEASURE_NAME>"
    "<DESCRIPTION>Share of revenue retained.</DESCRIPTION>"
    "<EXPRESSION>DIVIDE([Margin], [Total Sales])</EXPRESSION>"
    "<MEASURE_IS_VISIBLE>false</MEASURE_IS_VISIBLE>"
    "</row>"
)


def test_definitions_are_keyed_by_the_name_mdschema_uses():
    got = measure_definitions(AGGREGATE)
    assert list(got) == ["Total Sales"]
    definition = got["Total Sales"]
    assert "Technical definition" in definition.description
    assert definition.display_folder == "Sales"
    assert definition.format_string == "#,0"
    assert definition.visible is True
    # A plain aggregate has no formula of its own; the aggregation is structural.
    assert definition.expression == ""


def test_a_calculated_measure_carries_the_servers_expression():
    definition = measure_definitions(CALCULATED)["Margin %"]
    assert definition.expression == "DIVIDE([Margin], [Total Sales])"
    assert definition.visible is False


def test_an_empty_or_refused_rowset_is_not_an_error():
    assert measure_definitions("") == {}
    assert measure_definitions(_rowset("")) == {}
    assert measure_definitions("<Fault><faultstring>no</faultstring></Fault>") == {}


def _planned_columns(definitions):
    model = parse_csdl((FIX / "discover.DISCOVER_CSDL_METADATA.xml").read_text())
    plan, _ = plan_tabular(
        model=model,
        service="ssas_tabular",
        database="AWTabular",
        measure_definitions=definitions,
    )
    return {column.name: column for table in plan.schemas[0].tables for column in table.columns}


def test_the_join_goes_through_the_reference_name_not_the_column_name():
    """The crux. The CSDL column is `Total_Sales` and MDSCHEMA says `Total Sales`,
    so a join on the column name matches nothing and every description silently
    stays the bare word "measure" -- which looks exactly like "the server told us
    nothing"."""
    definitions = measure_definitions(AGGREGATE)
    assert "Total_Sales" not in definitions  # the name a naive join would use

    columns = _planned_columns(definitions)
    assert columns["Total_Sales"].is_measure
    assert "Value of goods invoiced" in columns["Total_Sales"].description
    assert "SUM(FactInternetSales[SalesAmount])" in columns["Total_Sales"].description


def test_a_measure_with_no_definition_keeps_the_old_description():
    """An enrichment that is absent must not read as an enrichment that is empty."""
    columns = _planned_columns({})
    assert columns["Total_Sales"].description == "measure"


def test_an_expression_is_appended_under_its_own_label():
    definitions = measure_definitions(
        _rowset(
            "<row><MEASURE_NAME>Total Sales</MEASURE_NAME>"
            "<DESCRIPTION>Invoiced value.</DESCRIPTION>"
            "<EXPRESSION>SUMX(Fact, Fact[Qty] * Fact[Price])</EXPRESSION></row>"
        )
    )
    description = _planned_columns(definitions)["Total_Sales"].description
    assert description.startswith("Invoiced value.")
    assert "Expression:\nSUMX(Fact, Fact[Qty] * Fact[Price])" in description


def test_non_measure_columns_get_no_description():
    columns = _planned_columns(measure_definitions(AGGREGATE))
    assert columns["ProductKey"].description is None


def _csdl_without_reference_names() -> str:
    """The recorded CSDL with the bi:Measure annotation stripped of its names.

    Some models' CSDL carries `<bi:Measure/>` with no ReferenceName and no
    Caption. The column is still identifier-safe (`Total_Sales`), so the only key
    left is one MDSCHEMA never uses.
    """
    import re

    raw = (FIX / "discover.DISCOVER_CSDL_METADATA.xml").read_text()
    return re.sub(r"<bi:Measure[^>]*/>", "<bi:Measure/>", raw)


def test_the_canonical_spelling_is_the_fallback_when_the_annotation_is_missing():
    """Underscores against spaces is the whole difference, and a model that omits
    the annotation would otherwise show every measure as the bare word "measure" --
    indistinguishable from a model that documents nothing."""
    model = parse_csdl(_csdl_without_reference_names())
    measure = next(c for t in model.tables for c in t.columns if c.is_measure)
    assert measure.name == "Total_Sales"
    assert measure.reference_name == "", "this fixture is only interesting without it"

    plan, _ = plan_tabular(
        model=model,
        service="s",
        database="d",
        measure_definitions=measure_definitions(AGGREGATE),
    )
    column = next(c for t in plan.schemas[0].tables for c in t.columns if c.is_measure)
    assert "SUM(FactInternetSales[SalesAmount])" in column.description


def test_an_ambiguous_canonical_match_is_refused():
    """A model holding both spellings would have them silently swapped, which is
    worse than the missing description the fallback exists to prevent."""
    from ssas_om.csdl import Column
    from ssas_om.mapper_tabular import _find_definition

    both = measure_definitions(
        _rowset(
            "<row><MEASURE_NAME>Gross Margin</MEASURE_NAME><DESCRIPTION>spaces</DESCRIPTION></row>"
            "<row><MEASURE_NAME>Gross_Margin</MEASURE_NAME><DESCRIPTION>underscore</DESCRIPTION></row>"
        )
    )
    # an exact key still wins
    exact = Column("Gross_Margin", "Edm.Double", "DOUBLE", True, is_measure=True)
    assert _find_definition(exact, both).description == "underscore"
    # but a column matching neither exactly gets nothing rather than a coin toss
    ambiguous = Column("gross margin", "Edm.Double", "DOUBLE", True, is_measure=True)
    assert _find_definition(ambiguous, both) is None


def test_the_rest_of_the_row_is_appended_under_its_own_heading():
    """Five cells of about fifteen were acted on and the rest discarded, so a
    reader of the catalog saw this connector's selection rather than what the model
    says. Everything else the server sent is now reproduced, in its order."""
    definitions = measure_definitions(AGGREGATE)
    description = _planned_columns(definitions)["Total_Sales"].description

    # what was already rendered stays where it was, and is not repeated raw
    assert description.startswith("Business definition:")
    assert description.count("Technical definition:") == 1
    # and the rest arrives verbatim, in the server's order, keys code-formatted
    block = description.split("**MDSCHEMA_MEASURES**")[1]
    assert block.index("`CATALOG_NAME`") < block.index("`CUBE_NAME`")
    assert "`MEASURE_DISPLAY_FOLDER`: Sales" in block
    assert "`DEFAULT_FORMAT_STRING`: #,0" in block
    assert "`DESCRIPTION`" not in block, "already shown above; repeating it is noise"


def test_the_expression_is_not_repeated_in_the_raw_block():
    definitions = measure_definitions(CALCULATED)
    definition = definitions["Margin %"]
    from ssas_om.mapper_tabular import _rowset_block

    block = _rowset_block(definition)
    assert "`EXPRESSION`" not in block
    assert "`MEASURE_IS_VISIBLE`: false" in block


def test_the_raw_block_can_be_turned_off():
    """A noisy default is still a default; a service that does not want fifteen
    lines per measure says so once."""
    quiet = measure_definitions(AGGREGATE, include_fields=False)
    description = _planned_columns(quiet)["Total_Sales"].description
    assert "SUM(FactInternetSales[SalesAmount])" in description
    assert "MDSCHEMA_MEASURES" not in description
