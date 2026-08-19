# Step 0 — discovery report

Probed both msmdpump endpoints with the read-only account, every rowset via both Discover
(by RequestType) and Execute (`SELECT * FROM $SYSTEM.<ROWSET>` + Catalog). 42 scrubbed
fixtures under `tests/fixtures/xmla/`. Zero identifying tokens leak (verified).

## 1. What answered, what faulted

| rowset family | tabular endpoint | multidimensional endpoint |
|---|---|---|
| DISCOVER_DATASOURCES, DBSCHEMA_CATALOGS, DISCOVER_SCHEMA_ROWSETS | ok | ok |
| TMSCHEMA_* (9 probed) | **FAULT — admin required** | ok but 0 rows (no tabular objects) |
| MDSCHEMA_* (9 probed) | ok, with data | ok, with data |

The TMSCHEMA fault is explicit: *"User '…' needs to be an administrator to read the
metadata of the database 'AWTabular'."* (`ErrorCode 0xC1180076`). So for a least-privilege
reader, TMSCHEMA is unusable; MDSCHEMA is the only viable interface — and it works for
both model kinds.

## 2. How the schema arrives; is the inline XSD reliable?

Every response embeds a full `xsd:schema` (rowset namespace) that types each column
(`xsd:string|int|long|dateTime|boolean|unsignedInt`, plus a `uuid` simpleType). Reliable
for typing the **DMV** columns — parse rows straight from it.

Caveat that matters for mapping: the inline XSD types the DMV's own columns, *not* the
model's data-column SQL types. A model column's type comes from a rowset **field** —
`MDSCHEMA_LEVELS.LEVEL_DBTYPE` (OLE DB type code: 130=WChar, 20=BigInt, 3=Int, 5=Double,
…) and `MDSCHEMA_MEASURES.MEASURE_DATA_TYPE`. So: XSD for parsing, LEVEL_DBTYPE for
column typing.

## 3. Model-detection signal (replaces the brief's guess)

The brief guessed "probe TMSCHEMA_MODEL, fall back". That faults for a reader. Replace with
`DBSCHEMA_CATALOGS`:

| | tabular | multidimensional |
|---|---|---|
| `TYPE` | 3 | 0 |
| `COMPATIBILITY_LEVEL` | 1600 | 1100 |
| cube name (`MDSCHEMA_CUBES`) | always `Model` | the real cube name (`AWCube`) |

`TYPE` alone classifies; no admin-only rowset needed.

## 4. Does MD give enough to map cubes / measure groups / dimensions?

Yes, entirely, for the reader:
- `MDSCHEMA_CUBES` → the cube; `MDSCHEMA_MEASUREGROUPS` → measure groups;
  `MDSCHEMA_DIMENSIONS` → dimensions; `MDSCHEMA_MEASURES` (with `MEASUREGROUP_NAME`) →
  measures; `MDSCHEMA_HIERARCHIES`/`_LEVELS` → attributes/columns;
  `MDSCHEMA_MEASUREGROUP_DIMENSIONS` → which dimensions relate to which measure group.
- The same rowsets describe the tabular model (tables surface as `DIMENSION_TYPE=3`
  dimensions, each also a measure group; columns as `HIERARCHY_ORIGIN=2` hierarchies). So
  a single MDSCHEMA extractor covers both modes, differing only in interpretation.

Observed shapes:
- Tabular `AWTabular`: cube `Model`; dimensions DimProduct (606), FactInternetSales
  (60398), Measures; measures `Total Sales` (+ a hidden `__Default measure`); measure
  groups DimProduct, FactInternetSales. Columns e.g. FactInternetSales →
  {OrderQuantity, ProductKey, SalesAmount}.
- Multidimensional `AWMultidim`: cube `AWCube`; dimensions Product (607), Measures;
  measure `Sales Amount`; measure group `Internet Sales`.

## 5. What the observed responses contradict in the brief

1. **TMSCHEMA-based tabular extraction is not viable for a least-privilege reader.** It is
   admin-gated. Either build on MDSCHEMA, or use an SSAS admin account (trade-off below).
2. **Tabular "tables and columns" are not TMSCHEMA_TABLES/_COLUMNS here** — they are
   MDSCHEMA dimensions + attribute-hierarchies.
3. **`DISCOVER_SCHEMA_ROWSETS` advertises 50 TMSCHEMA rowsets a reader cannot query.** The
   advertised catalog ≠ the usable capability; capability must be probed with the real
   account, not read from the advertised list.

## Open questions — RESOLVED

- A (access model) → **MDSCHEMA only, read-only**.
- B (OM version) → **1.13.3**.
- C (column typing) → coarse STRING/NUMBER/DATE/BOOLEAN for M1 (default; unobjected).
- D (MD mapping) → **cube-specific shape**.
- E (MSSQL account) → dedicated read-only SQL login (default; unobjected).

Original list, for the record:

A. **Least-privilege vs fidelity.** TMSCHEMA (needs admin) gives exact tabular types,
   relationships, partitions, RLS roles. MDSCHEMA (reader) gives tables/columns/measures
   with OLE DB type codes and less tabular-native detail. Keep `ssas_reader` + MDSCHEMA
   only, use an admin account for full TMSCHEMA, or hybrid (MDSCHEMA default, TMSCHEMA
   when admin)?
B. **OpenMetadata version** you run in production (prompt said confirm; else assume
   1.12.x).
C. **Column typing depth** for milestone 1 — full OLE DB→OpenMetadata type mapping, or a
   coarse STRING/NUMBER/DATE/BOOLEAN bucketing to start?
D. **MD cube mapping shape** — represent the cube as a database service too (measure
   groups + dimensions → tables, attributes/measures → columns), matching the tabular
   shape? Or a different representation for cubes?
E. **MSSQL account** — a dedicated read-only SQL login for the engine ingestion (parallel
   to `ssas_reader`), or is `sa` acceptable for the fixture?

## Addendum — normative-spec probing (DISCOVER_CSDL_METADATA)

Prompted by the normative references, probed the spec-defined metadata documents as the
read-only user:

- **`DISCOVER_CSDL_METADATA` — tabular: HTTP 200, reader-accessible.** Returns the model as
  CSDL ([MS-CSDLBI]): `EntityType` per table, `Property` per column with **exact EDM types**
  (Int64, String, Decimal — not OLE DB codes), measures as `bi:Measure`-annotated
  properties, and `Association` elements for relationships. A system `RowNumber_*` column is
  present and must be filtered.
- **`DISCOVER_CSDL_METADATA` — multidimensional: FAULT** ("the current model can only be
  expressed when the client is …"). CSDL is tabular-only.
- **`DISCOVER_XML_METADATA`** answers on both but returns the ASSL server/DB envelope, not
  per-object schema — not the extraction source.

**Design revision (supersedes the MDSCHEMA-for-tabular note above):** tabular extraction
uses `DISCOVER_CSDL_METADATA` ([MS-CSDLBI]); multidimensional uses `MDSCHEMA_*` ([MS-SSAS]).
Both reader-accessible, both spec-defined. Integer enums from MDSCHEMA are mapped per
[MS-SSAS-T].
