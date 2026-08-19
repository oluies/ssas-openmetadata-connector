"""[MS-SSAS] / [MS-SSAS-T] integer-enum maps → OpenMetadata type names.

The specs warn that DISCOVER responses carry *integer* enumeration values where TMSL
uses strings; the connector maps them here rather than guessing. Values are the plain
OpenMetadata `DataType` *names* (strings) so this module stays free of the heavy SDK;
the mappers convert them to the SDK enum.

References: [MS-SSAS], [MS-SSAS-T], and the Analysis Services schema-rowsets docs.
"""
from __future__ import annotations

# --- DBSCHEMA_CATALOGS.TYPE / cube source: model kind -------------------------------
CATALOG_KIND = {0: "multidimensional", 3: "tabular"}


def catalog_kind(type_code: int | str | None) -> str:
    try:
        return CATALOG_KIND.get(int(type_code), "unknown")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "unknown"


# --- OLE DB DBTYPE codes (multidimensional, MDSCHEMA_LEVELS.LEVEL_DBTYPE) ------------
# https://learn.microsoft.com/openspecs/... OLE DB DBTYPE enumeration.
_OLEDB_TO_OM = {
    2: "SMALLINT", 3: "INT", 20: "BIGINT", 18: "SMALLINT", 19: "INT", 21: "BIGINT",
    4: "FLOAT", 5: "DOUBLE",
    6: "DECIMAL", 131: "DECIMAL", 139: "DECIMAL",
    130: "STRING", 129: "STRING", 8: "STRING", 200: "STRING", 202: "STRING",
    11: "BOOLEAN",
    7: "DATETIME", 133: "DATE", 134: "TIME", 135: "DATETIME",
    72: "STRING",   # GUID
    128: "BINARY", 204: "BINARY",
}
OM_DEFAULT_TYPE = "STRING"  # safe fallback for an unknown code (FR-008)


def oledb_to_om_type(code: int | str | None) -> str:
    try:
        return _OLEDB_TO_OM.get(int(code), OM_DEFAULT_TYPE)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return OM_DEFAULT_TYPE


# --- EDM primitive types (tabular, CSDL Property Type) ------------------------------
_EDM_TO_OM = {
    "String": "STRING", "Int64": "BIGINT", "Int32": "INT", "Int16": "SMALLINT",
    "Byte": "SMALLINT", "Decimal": "DECIMAL", "Double": "DOUBLE", "Single": "FLOAT",
    "Boolean": "BOOLEAN", "DateTime": "DATETIME", "DateTimeOffset": "TIMESTAMP",
    "Time": "TIME", "Guid": "STRING", "Binary": "BINARY",
}


def edm_to_om_type(edm: str | None) -> str:
    if not edm:
        return OM_DEFAULT_TYPE
    return _EDM_TO_OM.get(edm.split(".")[-1], OM_DEFAULT_TYPE)


# --- MDSCHEMA_MEASURES.MEASURE_AGGREGATOR ------------------------------------------
MEASURE_AGGREGATOR = {
    0: "Unknown", 1: "Sum", 2: "Count", 3: "Min", 4: "Max", 5: "Avg",
    6: "Var", 7: "Std", 8: "DistinctCount", 9: "None", 127: "Calculated",
}


def aggregator_name(code: int | str | None) -> str:
    try:
        return MEASURE_AGGREGATOR.get(int(code), "Unknown")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "Unknown"


# --- MDSCHEMA_DIMENSIONS.DIMENSION_TYPE --------------------------------------------
DIMENSION_TYPE = {0: "Unknown", 1: "Time", 2: "Measure", 3: "Regular"}

# --- MDSCHEMA_HIERARCHIES.HIERARCHY_ORIGIN (bitmask) -------------------------------
HIERARCHY_ORIGIN_USER = 0x1
HIERARCHY_ORIGIN_ATTRIBUTE = 0x2  # attribute hierarchies == a dimension's columns
