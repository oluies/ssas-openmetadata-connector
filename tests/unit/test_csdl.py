from ssas_om.csdl import parse_csdl


def test_parses_tables_columns_measures_relationships(fixture_xml):
    model = parse_csdl(fixture_xml("tab", "discover.DISCOVER_CSDL_METADATA"))
    tables = {t.name: t for t in model.tables}
    assert set(tables) == {"DimProduct", "FactInternetSales"}

    # system RowNumber column filtered out
    dp_cols = {c.name: c for c in tables["DimProduct"].columns}
    assert set(dp_cols) == {"ProductKey", "EnglishProductName"}
    assert dp_cols["ProductKey"].om_type == "BIGINT"
    assert dp_cols["EnglishProductName"].om_type == "STRING"

    fis = tables["FactInternetSales"]
    fis_cols = {c.name: c for c in fis.columns}
    assert "RowNumber" not in " ".join(fis_cols)  # no RowNumber leaked in
    assert fis_cols["SalesAmount"].om_type == "DECIMAL"

    # measure detected via bi:Measure annotation
    measures = {c.name for c in fis.measures}
    assert "Total_Sales" in measures

    # one relationship: FactInternetSales (many) -> DimProduct (one)
    assert len(model.relationships) == 1
    rel = model.relationships[0]
    assert rel.from_table == "FactInternetSales" and rel.to_table == "DimProduct"
