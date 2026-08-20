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
