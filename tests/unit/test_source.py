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


# --- credential handling by authMechanism -------------------------------------
# These exercise the change directly rather than _requests_auth, which ignored
# user/password for kerberos both before and after -- so a test against it would
# have passed on the pre-change tree and proved nothing.

def _config(options: dict) -> dict:
    return {
        "type": "customDatabase",
        "serviceName": "ssas_tabular",
        "serviceConnection": {
            "config": {
                "type": "CustomDatabase",
                "sourcePythonClass": "ssas_om.source.SsasSource",
                "connectionOptions": options,
            }
        },
        "sourceConfig": {"config": {"type": "DatabaseMetadata"}},
    }


_BASE = {"host": "http://ssas.internal", "endpoint": "/olap-tab/msmdpump.dll"}


@pytest.mark.parametrize("mechanism", ["kerberos", "negotiate"])
def test_ticket_mechanisms_get_past_the_credential_check(mechanism):
    """Previously raised KeyError: 'user' before authMechanism was even read, so a
    Kerberos deployment had to put a dummy credential in the service config -- in
    clear text, and not the credential actually used.

    Without the [kerberos] extra installed the constructor still fails, but on the
    missing-extra message rather than on credentials. That distinction IS the fix:
    it proves user/password are no longer consulted on this path. Where the extra
    is present, construction succeeds outright.
    """
    try:
        src = SsasSource.create(_config({**_BASE, "authMechanism": mechanism}), MagicMock())
    except RuntimeError as exc:
        assert "extra" in str(exc)          # got past credentials to the dependency check
        assert "user" not in str(exc)
    except KeyError as exc:                  # the pre-fix behaviour
        pytest.fail(f"still demands credentials for {mechanism}: {exc}")
    else:
        assert src.client is not None


@pytest.mark.parametrize("mechanism", ["basic", "ntlm"])
def test_password_mechanisms_still_require_credentials(mechanism):
    with pytest.raises(KeyError) as excinfo:
        SsasSource.create(_config({**_BASE, "authMechanism": mechanism}), MagicMock())
    message = str(excinfo.value)
    assert "user" in message and "password" in message
    assert mechanism in message  # names the mechanism, not a bare KeyError


def test_default_mechanism_is_basic_and_requires_credentials():
    with pytest.raises(KeyError, match="basic"):
        SsasSource.create(_config(dict(_BASE)), MagicMock())


def test_basic_auth_source_constructs_with_credentials():
    """The ordinary path still works -- the guard did not break it."""
    src = SsasSource.create(
        _config({**_BASE, "user": "reader", "password": "pw"}), MagicMock()
    )
    assert src.client is not None


# --- the default mechanism follows the transport -------------------------------
# HTTP Basic is msmdpump's IIS front end; the native binding speaks GSS-API only.
# A single global default would make one of the two transports fail on a setting
# the operator never wrote.

_TCP_BASE = {"host": "ssas.internal", "transport": "tcp", "port": "2383"}


def test_tcp_defaults_to_kerberos_and_asks_for_no_credentials():
    """With no authMechanism the tcp path must reach the connect attempt, not stop
    on a missing user/password -- which is what a 'basic' default would have done."""
    try:
        SsasSource.create(_config(dict(_TCP_BASE)), MagicMock())
    except KeyError as exc:
        pytest.fail(f"tcp default still demands credentials: {exc}")
    except (RuntimeError, OSError, ConnectionError):
        pass  # missing [tcp] extra, or no server -- both are past the config check


def test_tcp_rejects_basic_before_touching_the_network():
    from ssas_om.tcp_client import resolve_mechanism  # noqa: F401  (documents the origin)

    with pytest.raises(ValueError, match="basic"):
        SsasSource.create(
            _config({**_TCP_BASE, "authMechanism": "basic",
                     "user": "reader", "password": "pw"}),
            MagicMock(),
        )


def test_tcp_requires_a_pinned_port():
    """There is no default: guessing between a default instance's well-known port
    and a named instance's pinned one presents to the operator as a hang."""
    with pytest.raises(KeyError, match="port"):
        SsasSource.create(
            _config({"host": "ssas.internal", "transport": "tcp"}), MagicMock()
        )


def test_unknown_transport_is_rejected():
    with pytest.raises(ValueError, match="carrier"):
        SsasSource.create(
            _config({**_BASE, "transport": "carrier", "user": "r", "password": "p"}),
            MagicMock(),
        )


def test_http_still_demands_an_endpoint_and_says_which_option():
    """Relaxing `endpoint` for tcp must not make it optional for http, where a
    missing msmdpump path would otherwise POST to the bare host."""
    with pytest.raises(KeyError, match="endpoint"):
        SsasSource.create(
            _config({"host": "http://ssas.internal", "user": "r", "password": "p"}),
            MagicMock(),
        )


# --- the password can come from the environment instead of the config ----------
# connectionOptions is dict[str, str] in the OpenMetadata schema with no password
# format, so a literal password is stored unencrypted and returned by the API to
# anyone who may view the service. A variable NAME is not a credential.

def test_password_can_come_from_an_environment_variable(monkeypatch):
    monkeypatch.setenv("SSAS_PW_FOR_TEST", "from-the-runtime")
    src = SsasSource.create(
        _config({**_BASE, "user": "reader", "passwordEnvVar": "SSAS_PW_FOR_TEST"}),
        MagicMock(),
    )
    assert src.client is not None


def test_a_missing_environment_variable_says_who_supplies_it(monkeypatch):
    """The value comes from the runtime, not OpenMetadata, so the error has to
    point at the runtime or the operator looks in the wrong place."""
    monkeypatch.delenv("SSAS_PW_ABSENT", raising=False)
    with pytest.raises(KeyError) as excinfo:
        SsasSource.create(
            _config({**_BASE, "user": "reader", "passwordEnvVar": "SSAS_PW_ABSENT"}),
            MagicMock(),
        )
    message = str(excinfo.value)
    assert "SSAS_PW_ABSENT" in message
    assert "Kubernetes Secret" in message or "runtime" in message


def test_an_empty_environment_variable_is_treated_as_missing(monkeypatch):
    monkeypatch.setenv("SSAS_PW_EMPTY", "")
    with pytest.raises(KeyError, match="SSAS_PW_EMPTY"):
        SsasSource.create(
            _config({**_BASE, "user": "reader", "passwordEnvVar": "SSAS_PW_EMPTY"}),
            MagicMock(),
        )


def test_setting_both_password_and_passwordEnvVar_is_refused(monkeypatch):
    """Not a precedence rule: an operator who edited the wrong one would see no
    change and no message, and would still be using the credential they thought
    they had replaced."""
    monkeypatch.setenv("SSAS_PW_BOTH", "from-env")
    with pytest.raises(KeyError, match="both"):
        SsasSource.create(
            _config({**_BASE, "user": "reader", "password": "literal",
                     "passwordEnvVar": "SSAS_PW_BOTH"}),
            MagicMock(),
        )


def test_a_literal_password_still_works(monkeypatch):
    """The existing path is unchanged; passwordEnvVar is additive."""
    src = SsasSource.create(
        _config({**_BASE, "user": "reader", "password": "pw"}), MagicMock()
    )
    assert src.client is not None


def test_the_env_var_name_is_not_treated_as_the_password(monkeypatch):
    """Guards the obvious slip: reading opts['passwordEnvVar'] as the value."""
    from ssas_om.source import _password_from

    monkeypatch.setenv("SSAS_PW_NAMED", "the-real-secret")
    assert _password_from({"passwordEnvVar": "SSAS_PW_NAMED"}) == "the-real-secret"
