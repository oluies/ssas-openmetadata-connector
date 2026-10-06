"""The native-TCP transport adapter.

Runs without the [tcp] extra installed: the adapter is exercised through a fake
session, so these stay in the SDK-free offline suite.
"""

import pytest

from ssas_om.client import XmlaResult
from ssas_om.tcp_client import _as_rowset_xml, _restrictions_to_mapping


def test_restriction_fragments_are_parsed_into_a_mapping():
    """The HTTP client takes restrictions as raw XML; the TCP library takes a
    mapping and escapes it, so the fragment must be parsed rather than forwarded."""
    got = _restrictions_to_mapping(
        "<CATALOG_NAME>AWTabular</CATALOG_NAME><PERSPECTIVE_NAME></PERSPECTIVE_NAME>"
    )
    assert got == {"CATALOG_NAME": "AWTabular", "PERSPECTIVE_NAME": ""}


def test_empty_restrictions_are_fine():
    assert _restrictions_to_mapping("") == {}
    assert _restrictions_to_mapping(None) == {}


def test_rows_are_rendered_as_rowset_xml_the_existing_parsers_read():
    """Re-rendering keeps ONE parsing path for both bindings, rather than
    branching every consumer on which transport produced the data."""
    from ssas_om.client import parse_rowset

    xml = _as_rowset_xml([{"CATALOG_NAME": "AWTabular", "DESC": "a & b"}])
    rows = parse_rowset(xml)
    assert rows == [{"CATALOG_NAME": "AWTabular", "DESC": "a & b"}]


def test_rendered_values_are_escaped():
    xml = _as_rowset_xml([{"N": "<script>"}])
    assert "&lt;script&gt;" in xml


class _FakeSession:
    def __init__(self, error=None, rows=None):
        self._error = error
        self._rows = rows or []

    def discover(self, request_type, restrictions=None, catalog=None):
        if self._error:
            raise self._error
        return self._rows

    def execute(self, statement, catalog=None):
        if self._error:
            raise self._error
        return self._rows

    def close(self):
        pass


def _adapter_with(session):
    """Build the adapter without connecting, then swap in a fake session."""
    from ssas_om.tcp_client import TcpXmlaClient

    obj = TcpXmlaClient.__new__(TcpXmlaClient)
    obj._session = session
    obj._scrub = lambda t: t
    return obj


@pytest.mark.parametrize(
    "error_name,expected_status",
    [
        ("AuthorizationError", 403),
        ("AuthenticationError", 401),
        ("ConnectionError", 503),
        ("ServerError", 200),
    ],
)
def test_typed_errors_become_faults_not_exceptions(error_name, expected_status):
    """The Source reads .ok and .fault, so a refusal must arrive as a fault. The
    status codes mirror what the HTTP binding returns for the same condition, so
    existing callers keep their meaning."""
    ssas_xmla = pytest.importorskip("ssas_xmla")
    error_cls = getattr(ssas_xmla, error_name)
    adapter = _adapter_with(_FakeSession(error=error_cls("refused")))
    result = adapter.discover("DBSCHEMA_CATALOGS")
    assert isinstance(result, XmlaResult)
    assert result.status == expected_status
    assert result.fault and "refused" in result.fault
    assert not result.ok


def test_a_successful_discover_is_ok_and_parses():
    pytest.importorskip("ssas_xmla")
    from ssas_om.client import parse_rowset

    adapter = _adapter_with(_FakeSession(rows=[{"CATALOG_NAME": "AWTabular"}]))
    result = adapter.discover("DBSCHEMA_CATALOGS")
    assert result.ok
    assert parse_rowset(result.text) == [{"CATALOG_NAME": "AWTabular"}]


def test_dmv_builds_the_system_rowset_query():
    pytest.importorskip("ssas_xmla")
    seen = {}

    class Recording(_FakeSession):
        def execute(self, statement, catalog=None):
            seen["statement"] = statement
            return []

    _adapter_with(Recording()).dmv("MDSCHEMA_CUBES", catalog="AWMultidim")
    assert seen["statement"] == "SELECT * FROM $SYSTEM.MDSCHEMA_CUBES"


# --- authMechanism on the native binding --------------------------------------
# The two bindings do not offer the same set of mechanisms, which is the one place
# they are not interchangeable. These run without the [tcp] extra because
# resolve_mechanism is checked before the optional import.


def test_basic_is_rejected_rather_than_coerced_to_a_ticket_login():
    """The earlier version mapped basic -> kerberos, which discarded the supplied
    password and authenticated as whoever held a ticket. A silently different
    identity is worse than a refusal, so the refusal is the tested behaviour."""
    from ssas_om.tcp_client import resolve_mechanism

    with pytest.raises(ValueError) as excinfo:
        resolve_mechanism("basic", "pw")
    message = str(excinfo.value)
    assert "basic" in message
    assert "ntlm" in message and "kerberos" in message  # names the alternatives


def test_unknown_mechanism_names_the_accepted_set():
    from ssas_om.tcp_client import resolve_mechanism

    with pytest.raises(ValueError, match="digest"):
        resolve_mechanism("digest", "pw")


def test_ntlm_without_a_password_is_refused():
    """NTLM derives its key from the password and cannot read a ticket cache, so
    an empty password would fail at the handshake with a far less useful error."""
    from ssas_om.tcp_client import resolve_mechanism

    with pytest.raises(ValueError, match="password"):
        resolve_mechanism("ntlm", "")


@pytest.mark.parametrize("mechanism", ["kerberos", "negotiate"])
def test_ticket_mechanisms_need_no_password(mechanism):
    from ssas_om.tcp_client import resolve_mechanism

    assert resolve_mechanism(mechanism, "") == mechanism


def test_mechanism_is_case_insensitive_and_defaults_to_kerberos():
    from ssas_om.tcp_client import resolve_mechanism

    assert resolve_mechanism("NTLM", "pw") == "ntlm"
    assert resolve_mechanism(None, "") == "kerberos"
    assert resolve_mechanism("", "") == "kerberos"


def _stub_library(monkeypatch):
    """Install a stand-in `ssas_xmla` carrying only the error classes `_run` imports.

    The adapter's typed-error mapping is the only thing it needs the library for on
    this path, and `importorskip` would make these tests SKIP in CI, where the [tcp]
    extra is not installed — so the one test that catches a lost CSDL document would
    never run anywhere it matters.
    """
    import sys
    import types

    stub = types.ModuleType("ssas_xmla")
    for name in (
        "AuthorizationError",
        "AuthenticationError",
        "ConnectionError",
        "ServerError",
        "SsasError",
    ):
        setattr(stub, name, type(name, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "ssas_xmla", stub)
    return stub


def _csdl_cell(fixture_xml, whole_cell: bool = True) -> str:
    """The METADATA cell as the library hands it over, taken from the recorded HTTP
    response so the shape is a real server's and not this test's idea of one.

    Both shapes are exercised, because both exist in the wild of our own versions:
    ssas-xmla-tcp v0.1.1 serialises the cell's CHILDREN, and v0.1.2 onwards
    serialises the CELL (a cell with several children is otherwise a multi-root
    fragment that does not parse). The adapter must not care which it is given, and
    neither must `parse_csdl`. The children shape stays exercised because the pin
    is ours to move: an image still built against v0.1.1 hands over that shape.
    """
    import xml.etree.ElementTree as ET

    raw = fixture_xml("tab", "discover.DISCOVER_CSDL_METADATA")
    root = ET.fromstring(raw)
    cell = next(el for el in root.iter() if el.tag.rsplit("}", 1)[-1] == "METADATA")
    if whole_cell:
        return ET.tostring(cell, encoding="unicode")
    return "".join(ET.tostring(child, encoding="unicode") for child in cell)


@pytest.mark.parametrize("whole_cell", [True, False], ids=["cell", "children"])
def test_a_csdl_document_survives_the_adapter_and_parses_to_tables(
    fixture_xml, monkeypatch, whole_cell
):
    """The test that was missing. `test_client.py` asserted "EntityType" in r.text
    for the HTTP client only, so nothing covered the TCP path — which rendered the
    document back through the rowset renderer, escaped it, and produced a model
    with no tables at all while reporting success."""
    from ssas_om.csdl import parse_csdl

    _stub_library(monkeypatch)
    cell = _csdl_cell(fixture_xml, whole_cell=whole_cell)
    adapter = _adapter_with(_FakeSession(rows=[{"METADATA": cell}]))
    r = adapter.metadata_document(
        "DISCOVER_CSDL_METADATA",
        catalog="AWTabular",
        restrictions="<CATALOG_NAME>AWTabular</CATALOG_NAME>",
    )
    assert r.ok
    assert "EntityType" in r.text
    assert "&lt;EntityType" not in r.text, "the document was escaped, so it is now text"
    assert len(parse_csdl(r.text).tables) == 2


def test_the_document_column_is_named_not_guessed():
    """A rowset that happens to have one column must not be mistaken for a document,
    so the named column wins; the fallback exists only so a renamed column degrades
    to "the one value there is" rather than to silence."""
    from ssas_om.tcp_client import _as_document

    assert _as_document([{"CATALOG_NAME": "AWTabular", "METADATA": "<Schema/>"}]) == "<Schema/>"
    assert _as_document([{"SOMETHING_ELSE": "<Schema/>"}]) == "<Schema/>"
    assert _as_document([{"METADATA": ""}]) == ""
    assert _as_document([]) == ""


def test_a_refused_document_request_is_a_fault_not_an_empty_document(monkeypatch):
    """Otherwise "the server said no" and "the model is empty" are the same value,
    which is the confusion this whole path was built on."""
    errors = _stub_library(monkeypatch)

    adapter = _adapter_with(_FakeSession(error=errors.AuthorizationError("needs admin")))
    r = adapter.metadata_document("DISCOVER_CSDL_METADATA", catalog="AWTabular")
    assert not r.ok
    assert r.status == 403
    assert r.fault and "admin" in r.fault
    assert r.text == ""
