# Tasks: SSAS → OpenMetadata metadata connector

**Branch**: `001-ssas-openmetadata-metadata` | **Plan**: ./plan.md
One task per commit; after each, `roborev review HEAD` + `roborev wait`, read findings,
then continue. `[P]` = parallelizable (independent files). Priorities map to spec user
stories: P1 tabular (DoD), P2 MSSQL lineage source, P3 MD cube.

## Phase 0 — Foundation (blocks everything)

- **T001** Package skeleton: `src/ssas_om/` (empty modules per plan), `pyproject.toml`
  pinning `openmetadata-ingestion==1.13.3.*`, `requests`; `tests/` layout; ruff/mypy config.
- **T002** `tests/conftest.py`: disable sockets (`pytest-socket`), fixture loader that reads
  `tests/fixtures/xmla/<endpoint>/<name>.xml`. Assert the suite fails if a socket is opened.
- **T003** `src/ssas_om/redact.py` [P]: shared scrubber (host/IP/user/machine/SID/connstring)
  extracted from `probe.py`; unit test proves zero identifying tokens on a sample. Wire a
  `tests/test_no_leak.py` gate that scans all committed fixtures.
- **T004** `src/ssas_om/enums.py` [P]: [MS-SSAS]/[MS-SSAS-T] integer-enum maps
  (catalog `TYPE`, `DIMENSION_TYPE`, `HIERARCHY_ORIGIN`, `MEASURE_AGGREGATOR`, OLE DB
  `LEVEL_DBTYPE`, EDM type names) → OpenMetadata column types / meanings; table-driven test.

## Phase 1 — XMLA client (blocks parsers)

- **T005** `src/ssas_om/client.py`: Discover/Execute over HTTP Basic; SOAPAction headers;
  catalog + restriction support; fault detection returning a typed result; never logs bodies
  or auth. Unit tests drive it against the stub only.
- **T006** `docker/ssas-stub/` [P]: tiny HTTP server that replays `tests/fixtures/xmla` keyed
  by (endpoint, RequestType/rowset); used by client + integration tests without the host.

## Phase 2 — Extraction (P1 tabular first)

- **T007** `src/ssas_om/classify.py`: parse `DBSCHEMA_CATALOGS`; map `TYPE` via enums to
  {tabular, multidimensional}. Test against both catalog fixtures.
- **T008** `src/ssas_om/csdl.py` (P1): parse `DISCOVER_CSDL_METADATA` ([MS-CSDLBI]) →
  tables (EntityType), columns (Property + EDM type), measures (`bi:Measure`), relationships
  (Association); filter `RowNumber_*`. Test against the tab CSDL fixture (expects DimProduct,
  FactInternetSales, Total Sales, one association).
- **T009** `src/ssas_om/mdschema.py` (P3): parse MDSCHEMA rowsets → cube, measure groups,
  dimensions, measures, attribute columns (via hierarchies/levels), dim↔mg links. Test
  against the md fixtures.

## Phase 3 — Mapping to OpenMetadata

- **T010** `src/ssas_om/mapper_tabular.py` (P1): CSDL model → OM database service → schema →
  tables → columns (typed) + measures; table-level relationships recorded. Unit test asserts
  the emitted OM entities for the fixture model.
- **T011** `src/ssas_om/mapper_cube.py` (P3): MDSCHEMA model → OM Dashboard service +
  DashboardDataModel(s) (measures/dimension attributes as columns). Unit test on md fixture.
- **T012** `src/ssas_om/source.py` (P1): OpenMetadata ingestion Source entrypoint wiring
  client→classify→(csdl|mdschema)→mapper; per-object fault isolation (FR-006); manual
  one-shot run. Unit test drives a full tabular run against the stub.

## Phase 4 — Local stack & services

- **T013** `docker/compose.yml`: OpenMetadata 1.13.3 server + datastore + search + the
  connector image from the ingestion base. No SQL/SSAS services. `.env`-driven.
- **T014** MSSQL service registration (P2): built-in MSSQL connector config for
  AdventureWorksDW2022 (creds from `.env`); documented run. Table-level lineage target.
- **T015** SSAS service registration (P1): ingestion config for this connector against the
  tabular endpoint; `docker compose up -d` + one run → database service with tables/columns
  visible (milestone-1 DoD acceptance).

## Phase 5 — Lineage & verification

- **T016** (P2) Table-level SSAS→MSSQL lineage: link each tabular table to its
  AdventureWorksDW source table (names align: DimProduct, FactInternetSales).
- **T017** Acceptance: scripted check that after `up -d` + tabular run, the OM API shows the
  service, tables and columns (SC-001); unit suite green with sockets disabled (SC-002);
  leak-gate green (SC-003); zero TMSCHEMA calls asserted (SC-004).

## Dependencies

- T001→T002→(T003,T004) foundation.
- T005 needs T001; T006 [P] with T005. Parsers (T007–T009) need T005/T006.
- Mappers (T010,T011) need their parser; T012 needs T007+T008+T010.
- T013 before T014/T015. T015 is the DoD gate. T016 needs T014+T015. T017 last.

## Milestone-1 exit (DoD)

T001–T008, T010, T012, T013, T015, T017 complete → `docker compose up -d` + one tabular
ingestion shows the tabular model's tables and columns in OpenMetadata; unit tests pass
with sockets disabled. (T009/T011 MD and T014/T016 lineage may trail into M2.)
