"""The stub's request→fixture routing is pure and unit-testable (no socket)."""
import importlib.util
from pathlib import Path

_STUB = Path(__file__).resolve().parents[2] / "docker" / "ssas-stub" / "stub.py"
_spec = importlib.util.spec_from_file_location("ssas_stub", _STUB)
stub = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stub)


def test_routes_discover_by_request_type():
    p = stub.resolve("tab", "<RequestType>DBSCHEMA_CATALOGS</RequestType>")
    assert p.name == "discover.DBSCHEMA_CATALOGS.xml"
    assert p.parent.name == "tab"


def test_routes_execute_by_dmv_rowset():
    p = stub.resolve("md", "SELECT * FROM $SYSTEM.MDSCHEMA_CUBES")
    assert p.name == "execute.MDSCHEMA_CUBES.xml"


def test_unroutable_returns_none():
    assert stub.resolve("tab", "<nonsense/>") is None


def test_resolved_fixtures_exist_on_disk():
    # the routing points at fixtures we actually recorded
    for endpoint, body, expect in [
        ("tab", "<RequestType>DBSCHEMA_CATALOGS</RequestType>", True),
        ("tab", "SELECT * FROM $SYSTEM.MDSCHEMA_CUBES", True),
    ]:
        p = stub.resolve(endpoint, body)
        assert p.exists() is expect
