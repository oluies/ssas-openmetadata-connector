from ssas_om.classify import catalogs_from_response


def test_tabular_catalog(fixture_xml):
    cats = catalogs_from_response(fixture_xml("tab", "discover.DBSCHEMA_CATALOGS"))
    assert len(cats) == 1
    assert cats[0].name == "AWTabular"
    assert cats[0].kind == "tabular"
    assert cats[0].compatibility_level == "1600"


def test_multidimensional_catalog(fixture_xml):
    cats = catalogs_from_response(fixture_xml("md", "discover.DBSCHEMA_CATALOGS"))
    assert cats[0].name == "AWMultidim"
    assert cats[0].kind == "multidimensional"
    assert cats[0].compatibility_level == "1100"
