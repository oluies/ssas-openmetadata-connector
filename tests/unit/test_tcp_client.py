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
