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


def test_auth_mechanism_selection():
    import pytest as _pytest

    from ssas_om.client import _requests_auth
    assert _requests_auth("basic", "u", "p") == ("u", "p")
    with _pytest.raises(ValueError):
        _requests_auth("saml", "u", "p")


def test_kerberos_accepts_empty_credentials():
    """The mechanism authenticates from the ambient ticket cache, so the Source no
    longer demands credentials for it -- requiring them forced a dummy pair into the
    service config where it sat in clear text doing nothing.

    With the extra absent this reaches the install-hint error rather than failing on
    the empty credentials, which is exactly the point: user/password are never
    consulted on this path.
    """
    import pytest

    from ssas_om.client import _requests_auth

    try:
        handler = _requests_auth("kerberos", "", "")
    except RuntimeError as exc:
        assert "[kerberos]" in str(exc)  # got past credentials to the extra check
    else:
        assert handler is not None
        del pytest


def test_basic_still_uses_both():
    from ssas_om.client import _requests_auth

    assert _requests_auth("basic", "u", "p") == ("u", "p")
