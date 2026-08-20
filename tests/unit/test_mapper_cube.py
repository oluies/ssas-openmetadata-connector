from ssas_om.mapper_cube import plan_cube
from ssas_om.mdschema import build_cube


def test_plan_cube_from_md_fixtures(fixture_xml):
    def f(n):
        return fixture_xml("md", n)

    cube = build_cube(
        f("execute.MDSCHEMA_CUBES"), f("execute.MDSCHEMA_MEASUREGROUPS"),
        f("execute.MDSCHEMA_DIMENSIONS"), f("execute.MDSCHEMA_LEVELS"),
        f("execute.MDSCHEMA_MEASURES"),
    )
    svc = plan_cube(cube, service="ssas_md", database="AWMultidim")
    assert svc.service_type == "database"
    assert svc.schemas[0].name == "AWCube"
    names = {t.name for t in svc.schemas[0].tables}
    assert "Product" in names and "Measures" in names
    measures_tbl = next(t for t in svc.schemas[0].tables if t.name == "Measures")
    assert any(c.name == "Sales Amount" and c.is_measure for c in measures_tbl.columns)
