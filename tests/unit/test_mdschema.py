from ssas_om.mdschema import build_cube


def _f(fx, name):
    return fx("md", name)


def test_build_cube_from_md_fixtures(fixture_xml):
    from ssas_om.mdschema import list_cube_names
    names = list_cube_names(_f(fixture_xml, "execute.MDSCHEMA_CUBES"))
    assert names == ["AWCube"]
    cube = build_cube(
        "AWCube",
        _f(fixture_xml, "execute.MDSCHEMA_MEASUREGROUPS"),
        _f(fixture_xml, "execute.MDSCHEMA_DIMENSIONS"),
        _f(fixture_xml, "execute.MDSCHEMA_LEVELS"),
        _f(fixture_xml, "execute.MDSCHEMA_MEASURES"),
    )
    assert cube.name == "AWCube"
    assert "Internet Sales" in cube.measure_groups
    # Measures dimension excluded; Product remains
    dim_names = {d.name for d in cube.dimensions}
    assert "Product" in dim_names and "Measures" not in dim_names
    # visible measure
    assert any(m.name == "Sales Amount" for m in cube.measures)
    # Product dimension has attribute columns typed from LEVEL_DBTYPE
    product = next(d for d in cube.dimensions if d.name == "Product")
    assert product.columns  # e.g. EnglishProductName, ProductKey
