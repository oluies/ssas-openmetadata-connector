from ssas_om import enums


def test_catalog_kind():
    assert enums.catalog_kind(3) == "tabular"
    assert enums.catalog_kind("0") == "multidimensional"
    assert enums.catalog_kind(None) == "unknown"


def test_oledb_type_map_and_default():
    assert enums.oledb_to_om_type(130) == "STRING"   # WChar
    assert enums.oledb_to_om_type(20) == "BIGINT"     # I8
    assert enums.oledb_to_om_type(6) == "DECIMAL"     # currency
    assert enums.oledb_to_om_type(999) == enums.OM_DEFAULT_TYPE
    assert enums.oledb_to_om_type(None) == enums.OM_DEFAULT_TYPE


def test_edm_type_map():
    assert enums.edm_to_om_type("Int64") == "BIGINT"
    assert enums.edm_to_om_type("Edm.Decimal") == "DECIMAL"
    assert enums.edm_to_om_type("String") == "STRING"
    assert enums.edm_to_om_type("Weird") == enums.OM_DEFAULT_TYPE


def test_aggregator_and_dimension():
    assert enums.aggregator_name(1) == "Sum"
    assert enums.aggregator_name(127) == "Calculated"
    assert enums.DIMENSION_TYPE[2] == "Measure"
    assert enums.HIERARCHY_ORIGIN_ATTRIBUTE == 0x2
