"""SsasSource._iter emits the expected OpenMetadata entities from fixtures.

Requires the OpenMetadata SDK (source.py imports it); skipped where it is absent,
so the SDK-free offline suite is unaffected.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("metadata")

from ssas_om.client import XmlaClient  # noqa: E402
from ssas_om.source import SsasSource  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "xmla" / "tab"


def _fixture_transport(url, body, action):
    mapping = {
        "DBSCHEMA_CATALOGS": "discover.DBSCHEMA_CATALOGS.xml",
        "DISCOVER_CSDL_METADATA": "discover.DISCOVER_CSDL_METADATA.xml",
        "DISCOVER_DATASOURCES": "discover.DISCOVER_DATASOURCES.xml",
    }
    for marker, name in mapping.items():
        if marker in body:
            return 200, (FIX / name).read_text()
    return 500, "<Fault><faultstring>no fixture</faultstring></Fault>"


def _make_source():
    config = {
        "type": "customDatabase",
        "serviceName": "ssas_tabular",
        "serviceConnection": {
            "config": {
                "type": "CustomDatabase",
                "sourcePythonClass": "ssas_om.source.SsasSource",
                "connectionOptions": {
                    "host": "http://ssas.internal",
                    "endpoint": "/olap-tab/msmdpump.dll",
                    "user": "reader",
                    "password": "pw",
                    "catalog": "AWTabular",
                },
            }
        },
        "sourceConfig": {"config": {"type": "DatabaseMetadata"}},
    }
    src = SsasSource.create(config, MagicMock())
    src.client = XmlaClient("http://ssas.internal/olap-tab/msmdpump.dll",
                            "reader", "pw", transport=_fixture_transport)
    return src


def test_iter_emits_service_database_schema_tables():
    src = _make_source()
    entities = [e.right for e in src._iter() if e.right is not None]
    kinds = [type(e).__name__ for e in entities]
    assert kinds.count("CreateDatabaseServiceRequest") == 1  # hoisted, emitted once
    assert "CreateDatabaseRequest" in kinds
    assert "CreateDatabaseSchemaRequest" in kinds

    tables = [e for e in entities if type(e).__name__ == "CreateTableRequest"]
    by_name = {t.name.root: t for t in tables}
    assert set(by_name) == {"DimProduct", "FactInternetSales"}

    fis = by_name["FactInternetSales"]
    assert fis.databaseSchema.root == "ssas_tabular.AWTabular.Model"
    col_types = {c.name.root: c.dataType.value for c in fis.columns}
    assert col_types["SalesAmount"] == "DECIMAL"
    assert col_types["ProductKey"] == "BIGINT"


def test_test_connection_raises_on_fault():
    src = _make_source()

    def bad(url, body, action):
        return 401, '<soap:Fault><faultstring>Not Authorized</faultstring></soap:Fault>'

    src.client = XmlaClient("http://ssas.internal/olap-tab/msmdpump.dll",
                            "reader", "pw", transport=bad)
    with pytest.raises(ConnectionError):
        src.test_connection()


def _md_transport(url, body, action):
    md = Path(__file__).resolve().parents[1] / "fixtures" / "xmla" / "md"
    if "DBSCHEMA_CATALOGS" in body:
        return 200, (md / "discover.DBSCHEMA_CATALOGS.xml").read_text()
    import re
    m = re.search(r"\$SYSTEM\.([A-Z_]+)", body)
    if m:
        f = md / f"execute.{m.group(1)}.xml"
        if f.exists():
            return 200, f.read_text()
    return 200, "<root/>"


def test_iter_multidimensional_emits_database_from_cube():
    config = {
        "type": "customDatabase",
        "serviceName": "ssas_md",
        "serviceConnection": {"config": {
            "type": "CustomDatabase",
            "sourcePythonClass": "ssas_om.source.SsasSource",
            "connectionOptions": {
                "host": "http://ssas.internal", "endpoint": "/olap-md/msmdpump.dll",
                "user": "reader", "password": "pw", "catalog": "AWMultidim",
            },
        }},
        "sourceConfig": {"config": {"type": "DatabaseMetadata"}},
    }
    src = SsasSource.create(config, MagicMock())
    src.client = XmlaClient("http://ssas.internal/olap-md/msmdpump.dll",
                            "reader", "pw", transport=_md_transport)
    entities = [e.right for e in src._iter() if e.right is not None]
    kinds = [type(e).__name__ for e in entities]
    assert kinds.count("CreateDatabaseServiceRequest") == 1
    tables = {e.name.root for e in entities if type(e).__name__ == "CreateTableRequest"}
    assert "Product" in tables and "Measures" in tables


def test_iter_emits_lineage_edges_sql_to_ssas():
    import uuid
    config = {
        "type": "customDatabase",
        "serviceName": "ssas_tabular",
        "serviceConnection": {"config": {
            "type": "CustomDatabase",
            "sourcePythonClass": "ssas_om.source.SsasSource",
            "connectionOptions": {
                "host": "http://ssas.internal", "endpoint": "/olap-tab/msmdpump.dll",
                "user": "reader", "password": "pw", "catalog": "AWTabular",
                "lineageService": "hetzner_mssql",
                "lineageDatabase": "AdventureWorksDW2022",
                "lineageSchema": "dbo",
            },
        }},
        "sourceConfig": {"config": {"type": "DatabaseMetadata"}},
    }
    fqn_to_id: dict[str, uuid.UUID] = {}

    def get_by_name(entity, fqn):
        m = MagicMock()
        m.id = fqn_to_id.setdefault(fqn, uuid.uuid4())
        return m

    md = MagicMock()
    md.get_by_name.side_effect = get_by_name
    src = SsasSource.create(config, md)
    src.client = XmlaClient("http://ssas.internal/olap-tab/msmdpump.dll",
                            "reader", "pw", transport=_fixture_transport)

    edges = [e.right for e in src._iter()
             if e.right is not None and type(e.right).__name__ == "AddLineageRequest"]
    assert len(edges) == 2  # DimProduct, FactInternetSales

    def uid(x):
        return str(x.root if hasattr(x, "root") else x)

    got = {(uid(e.edge.fromEntity.id), uid(e.edge.toEntity.id)) for e in edges}
    for tbl in ("DimProduct", "FactInternetSales"):
        sql = fqn_to_id[f"hetzner_mssql.AdventureWorksDW2022.dbo.{tbl}"]
        ssas = fqn_to_id[f"ssas_tabular.AWTabular.Model.{tbl}"]
        # edge direction is SQL source -> SSAS target
        assert (str(sql), str(ssas)) in got


# A DAX EVALUATE rowset: element names are XML-name-encoded (`[`=_x005B_, `]`=_x005D_).
_DAX_ROWSET = (
    '<return xmlns="urn:schemas-microsoft-com:xml-analysis">'
    '<root xmlns="urn:schemas-microsoft-com:xml-analysis:rowset">'
    "<row><DimProduct_x005B_ProductKey_x005D_>1</DimProduct_x005B_ProductKey_x005D_>"
    "<DimProduct_x005B_EnglishProductName_x005D_>Road Bike"
    "</DimProduct_x005B_EnglishProductName_x005D_>"
    "<_x005B_RowNumber_x005D_>0</_x005B_RowNumber_x005D_></row>"
    "<row><DimProduct_x005B_ProductKey_x005D_>2</DimProduct_x005B_ProductKey_x005D_>"
    "<DimProduct_x005B_EnglishProductName_x005D_>Mountain Bike"
    "</DimProduct_x005B_EnglishProductName_x005D_>"
    "<_x005B_RowNumber_x005D_>1</_x005B_RowNumber_x005D_></row>"
    "</root></return>"
)


def _sample_transport(url, body, action):
    if "EVALUATE" in body:
        return 200, _DAX_ROWSET
    return _fixture_transport(url, body, action)


def test_sample_data_ingested_with_decoded_columns():
    src = _make_source()
    src.client = XmlaClient("http://ssas.internal/olap-tab/msmdpump.dll",
                            "reader", "pw", transport=_sample_transport)
    # drain the generator so the post-pass sample-data call runs
    list(src._iter())

    calls = src.metadata.ingest_table_sample_data.call_args_list
    assert calls, "expected sample data to be ingested"
    # bracket-encoded prefixes stripped, RowNumber dropped
    data = calls[0].kwargs["sample_data"]
    cols = [c.root if hasattr(c, "root") else c for c in data.columns]
    assert cols == ["ProductKey", "EnglishProductName"]
    assert data.rows == [["1", "Road Bike"], ["2", "Mountain Bike"]]


def test_sample_data_can_be_disabled():
    config = {
        "type": "customDatabase",
        "serviceName": "ssas_tabular",
        "serviceConnection": {"config": {
            "type": "CustomDatabase",
            "sourcePythonClass": "ssas_om.source.SsasSource",
            "connectionOptions": {
                "host": "http://ssas.internal", "endpoint": "/olap-tab/msmdpump.dll",
                "user": "reader", "password": "pw", "catalog": "AWTabular",
                "includeSampleData": "false",
            },
        }},
        "sourceConfig": {"config": {"type": "DatabaseMetadata"}},
    }
    src = SsasSource.create(config, MagicMock())
    src.client = XmlaClient("http://ssas.internal/olap-tab/msmdpump.dll",
                            "reader", "pw", transport=_sample_transport)
    list(src._iter())
    src.metadata.ingest_table_sample_data.assert_not_called()
