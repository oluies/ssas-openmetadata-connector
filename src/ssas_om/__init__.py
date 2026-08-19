"""Read-only OpenMetadata connector for SQL Server Analysis Services.

Tabular models are read via DISCOVER_CSDL_METADATA ([MS-CSDLBI]); multidimensional
models via MDSCHEMA ([MS-SSAS]). No admin-gated (TMSCHEMA) request is ever issued.
"""

__version__ = "0.1.0"
