# Normative references

Build the client against the protocol specifications, not blog posts. Where an observed
response disagrees with product documentation, these documents are the authority.

- **[MS-SSAS]** SQL Server Analysis Services Protocol — base protocol: Authenticate,
  Discover, Execute over SOAP/XMLA on TCP/HTTP/HTTPS; rowset column layouts for
  multidimensional models and for tabular at compatibility levels 1100/1103.
  https://learn.microsoft.com/en-us/openspecs/sql_server_protocols/ms-ssas/
- **[MS-SSAS-T]** Analysis Services Tabular Protocol — tabular at compatibility level 1200+:
  TMSCHEMA rowsets, tabular metadata objects, XMLA Create/Alter/Delete/Refresh, TMSL as
  JSON in the XMLA Statement element. **Warning we rely on:** DISCOVER results use *integer
  enumeration values* where TMSL uses strings — the connector MUST map those integers
  itself. https://learn.microsoft.com/en-us/openspecs/sql_server_protocols/ms-ssas-t/
- **[MS-CSDLBI]** Conceptual Schema Definition File Format with BI Annotations — the format
  returned by `DISCOVER_CSDL_METADATA`.
  https://learn.microsoft.com/en-us/openspecs/sql_data_portability/ms-csdlbi/
- **Analysis Services schema rowsets** (product docs landing page routing each rowset family
  to whichever protocol defines it).
  https://learn.microsoft.com/en-us/analysis-services/instances/analysis-services-schema-rowsets

## How these map to our observed, reader-accessible design

| model kind | interface | spec | why |
|---|---|---|---|
| tabular (compat 1600) | `DISCOVER_CSDL_METADATA` | [MS-CSDLBI] | reader-accessible; native tabular shape: EntityType→table, Property→column with **EDM type**, `bi:Measure`→measure, Association→relationship. TMSCHEMA is admin-gated (out of scope, [MS-SSAS-T]). |
| multidimensional | `MDSCHEMA_*` | [MS-SSAS] | reader-accessible; CSDL faults on MD ("model can only be expressed when the client is …"). |

Integer-enum mapping ([MS-SSAS-T] warning) applies to every MDSCHEMA integer we read —
`DIMENSION_TYPE`, `HIERARCHY_ORIGIN`, `MEASURE_AGGREGATOR`, `LEVEL_DBTYPE`, `CUBE`/catalog
`TYPE` — and MUST be mapped from the spec's enumerations, never guessed.
