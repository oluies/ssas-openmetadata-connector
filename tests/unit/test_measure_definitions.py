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
    return {
        column.name: column
        for table in plan.schemas[0].tables
        for column in table.columns
    }


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
