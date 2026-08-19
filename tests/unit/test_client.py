"""XmlaClient with an injected fixture transport — no network."""
from ssas_om.client import XmlaClient


def make_client(fixture_xml, endpoint, mapping):
    """mapping: dict of (marker-in-body) -> fixture name to return."""
    def transport(url, body, action):
        for marker, name in mapping.items():
            if marker in body:
                return 200, fixture_xml(endpoint, name)
        return 500, "<Envelope><Body><Fault><faultstring>no fixture</faultstring>" \
                    "</Fault></Body></Envelope>"
    return XmlaClient("http://host/olap", "user", "pw", transport=transport)


def test_discover_catalogs_ok(fixture_xml):
    c = make_client(fixture_xml, "tab", {"DBSCHEMA_CATALOGS": "discover.DBSCHEMA_CATALOGS"})
    r = c.discover("DBSCHEMA_CATALOGS")
    assert r.ok and r.fault is None
    assert "AWTabular" in r.text


def test_dmv_admin_fault_is_surfaced_and_scrubbed(fixture_xml):
    c = make_client(fixture_xml, "tab", {"TMSCHEMA_TABLES": "execute.TMSCHEMA_TABLES"})
    r = c.dmv("TMSCHEMA_TABLES", catalog="AWTabular")
    assert not r.ok
    assert r.fault is not None and "administrator" in r.fault
    # the fault reason must not leak the machine name
    assert "WIN-" not in r.fault


def test_csdl_discover_ok(fixture_xml):
    c = make_client(fixture_xml, "tab", {"CSDL": "discover.DISCOVER_CSDL_METADATA"})
    r = c.discover("DISCOVER_CSDL_METADATA", catalog="AWTabular",
                   restrictions="<CATALOG_NAME>AWTabular</CATALOG_NAME>")
    assert r.ok
    assert "EntityType" in r.text
