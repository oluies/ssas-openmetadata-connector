from ssas_om.csdl import parse_csdl
from ssas_om.mapper_tabular import plan_tabular


def test_plan_from_csdl_fixture(fixture_xml):
    model = parse_csdl(fixture_xml("tab", "discover.DISCOVER_CSDL_METADATA"))
    svc, rels = plan_tabular(model, service="ssas_tabular", database="AWTabular")

    assert svc.service_type == "database"
    assert svc.database == "AWTabular"
    assert len(svc.schemas) == 1 and svc.schemas[0].name == "Model"

    tables = {t.name: t for t in svc.schemas[0].tables}
    assert set(tables) == {"DimProduct", "FactInternetSales"}

    fis_cols = {c.name: c for c in tables["FactInternetSales"].columns}
    assert fis_cols["SalesAmount"].data_type == "DECIMAL"
    assert fis_cols["Total_Sales"].is_measure is True
    assert fis_cols["ProductKey"].is_measure is False

    # table-level relationship carried for lineage
    assert {(r.from_table, r.to_table) for r in rels} == {("FactInternetSales", "DimProduct")}

