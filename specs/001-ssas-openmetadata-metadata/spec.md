# Feature Specification: SSAS → OpenMetadata metadata connector

**Feature Branch**: `001-ssas-openmetadata-metadata`
**Created**: 2026-08-19
**Status**: Draft
**Input**: docs/spec-brief.md; docs/discovery-report.md (observed XMLA behaviour); docs/references.md (normative specs [MS-SSAS], [MS-SSAS-T], [MS-CSDLBI])

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Tabular model appears in the catalog (Priority: P1)

A data steward runs the connector against the tabular SSAS endpoint and sees, in the
OpenMetadata UI, a database service whose tables and columns mirror the tabular model —
each model table with its columns and types, and its measures — without the connector
ever holding administrator credentials.

**Why this priority**: This is the milestone-1 definition of done and the smallest slice
that delivers value: browsable tabular metadata in OpenMetadata.

**Independent Test**: Point the connector at the tabular endpoint (or the fixture stub),
run one ingestion, and confirm the service, its tables and columns exist in OpenMetadata.

**Acceptance Scenarios**:
1. **Given** the tabular model `AWTabular`, **When** ingestion runs, **Then** a database
   service is created containing tables `DimProduct` and `FactInternetSales` with their
   columns (e.g. FactInternetSales → ProductKey, SalesAmount, OrderQuantity).
2. **Given** a measure `Total Sales` on a table, **When** ingestion runs, **Then** it is
   represented on that table and hidden/system measures are excluded.
3. **Given** the connector's read-only account, **When** it queries metadata, **Then** it
   uses only MDSCHEMA and never a TMSCHEMA/admin-gated rowset.

### User Story 2 — Relational source ingested for lineage (Priority: P2)

The same steward registers the Hetzner SQL engine through OpenMetadata's built-in MSSQL
connector against AdventureWorksDW2022, so the tabular tables can later be linked to their
relational origin.

**Why this priority**: Lineage's target must exist before SSAS→SQL lineage is testable;
it is independent and reuses a built-in connector.

**Independent Test**: Run the MSSQL ingestion; confirm AdventureWorksDW2022's tables are in
OpenMetadata as a separate database service.

**Acceptance Scenarios**:
1. **Given** the engine credentials in `.env`, **When** MSSQL ingestion runs, **Then**
   AdventureWorksDW2022 tables (incl. DimProduct, FactInternetSales) appear as a service.

### User Story 3 — Multidimensional cube represented (Priority: P3)

The steward runs the connector against the multidimensional endpoint and sees the cube
represented in a cube-specific shape (cube, measure groups, dimensions, measures), distinct
from the tabular database-service shape.

**Why this priority**: Valuable but secondary to the tabular DoD; MD modelling has an open
representation question (see Requirements).

**Independent Test**: Run ingestion against the MD endpoint (or stub) and confirm the cube
`AWCube`, measure group `Internet Sales`, dimension `Product` and measure `Sales Amount`
are represented.

**Acceptance Scenarios**:
1. **Given** cube `AWCube`, **When** ingestion runs, **Then** its measure group, dimension
   and measure are represented with their relationships.

### Edge Cases

- A rowset returns a SOAP fault (e.g. admin-gated): the connector logs a scrubbed
  diagnostic and skips that object, never aborting the whole run.
- A model has zero visible measures, or a dimension with only a key attribute.
- The live host is unreachable: unit tests still pass (they use the stub, sockets off).
- Response rows carry an inline XSD but a column's model type must come from
  `MDSCHEMA_LEVELS.LEVEL_DBTYPE`; an unknown OLE DB type code maps to a safe default.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The connector MUST classify each catalog as tabular or multidimensional from
  `DBSCHEMA_CATALOGS.TYPE` (3 = tabular, 0 = multidimensional), then extract via CSDL
  (tabular) or MDSCHEMA (multidimensional). Classification uses no admin-gated rowset.
- **FR-002**: The connector MUST extract the tabular model from `DISCOVER_CSDL_METADATA`
  ([MS-CSDLBI]): each `EntityType` is a table, each `Property` a column with its EDM type;
  the system `RowNumber_*` column MUST be filtered out. (Reader-accessible; TMSCHEMA is
  admin-gated and out of scope.)
- **FR-003**: For tabular, measures MUST be identified by their `bi:Measure` annotation in
  the CSDL and attached to their owning table. For multidimensional, measures MUST come from
  `MDSCHEMA_MEASURES` linked via `MEASUREGROUP_NAME`; non-visible/system measures excluded.
- **FR-004**: The connector MUST map a tabular model to an OpenMetadata database service
  with tables and columns (milestone-1 DoD).
- **FR-005**: The connector MUST authenticate with Basic auth using read-only credentials
  from `.env`, and MUST NOT issue any TMSCHEMA or otherwise admin-gated request.
- **FR-006**: On a SOAP fault for one object, the connector MUST record a scrubbed
  diagnostic and continue; it MUST NOT emit host/IP/user/SID/connection strings anywhere.
- **FR-007**: The connector MUST be runnable against the fixture stub with no network, and
  the unit suite MUST pass with sockets disabled.
- **FR-008**: Tabular column types MUST map from the CSDL **EDM types** (exact:
  Int64/String/Decimal/DateTime/Boolean/…). Multidimensional column types MUST map from
  `MDSCHEMA_LEVELS.LEVEL_DBTYPE` OLE DB codes. Both map to OpenMetadata column types; an
  unknown code maps to a safe default.
- **FR-008a**: All DISCOVER integer enumerations (e.g. catalog `TYPE`, `DIMENSION_TYPE`,
  `HIERARCHY_ORIGIN`, `MEASURE_AGGREGATOR`, `LEVEL_DBTYPE`) MUST be mapped from the
  [MS-SSAS]/[MS-SSAS-T] enumerations, never guessed (the specs warn DISCOVER returns
  integers where TMSL uses strings).
- **FR-008b**: Tabular relationships MUST be read from CSDL `Association` elements and used
  to record intra-model table relationships.
- **FR-009**: The MSSQL engine MUST be ingested via OpenMetadata's built-in connector as a
  separate database service (lineage target).

Resolved during clarify:

- **FR-010**: The multidimensional cube MUST be represented as an OpenMetadata **Dashboard
  service with DashboardDataModel** entities — the cube as a data model, its measures and
  dimension attributes as the model's columns — distinct from the tabular database-service
  shape. (User Story 3.)
- **FR-011**: SSAS→MSSQL lineage MUST be **table-level** for milestone 1 (each SSAS table
  linked to its source SQL table); column-level lineage is deferred.
- **FR-012**: Ingestion for milestone 1 is a **manual one-shot run**; the OpenMetadata
  scheduler is deferred.

### Key Entities

- **SSAS catalog** — a model database; tabular or multidimensional (by `TYPE`).
- **Table** (tabular) / **Dimension, Measure group** (MD) — mapped from MDSCHEMA rowsets.
- **Column** — a tabular table's attribute hierarchy, or a dimension attribute.
- **Measure** — a visible measure, linked to its measure group.
- **OpenMetadata database service / table / column** — the ingested target entities.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After one ingestion of the tabular endpoint, the tabular model's tables and
  all their columns are visible in the OpenMetadata UI (milestone-1 DoD).
- **SC-002**: The unit suite passes with sockets disabled and no reachable host.
- **SC-003**: Zero identifying tokens (host, IP, user, machine name, SID, connection
  string) appear in any committed fixture or log, verified by an automated check.
- **SC-004**: The connector completes a full tabular ingestion issuing zero admin-gated
  (TMSCHEMA) requests.
- **SC-005**: A single object's fault does not abort the run; remaining objects still
  ingest.

## Assumptions

- OpenMetadata 1.13.3, local Docker; SQL Server and SSAS remote on Hetzner.
- Read-only `ssas_reader` (MDSCHEMA) is the only SSAS account; a dedicated read-only SQL
  login is preferred for the engine (default), `sa` acceptable as fallback for the fixture.
- The recorded fixtures under `tests/fixtures/xmla/` are the source of truth for tests.
