# Implementation Plan: SSAS → OpenMetadata metadata connector

**Branch**: `001-ssas-openmetadata-metadata` | **Spec**: ./spec.md
**Input**: spec.md; ../../docs/{spec-brief,discovery-report,references}.md

## Summary

A read-only OpenMetadata ingestion connector for SSAS. Tabular models are read via
`DISCOVER_CSDL_METADATA` ([MS-CSDLBI]) and mapped to an OpenMetadata database service
(tables/columns/measures/relationships). Multidimensional cubes are read via `MDSCHEMA_*`
([MS-SSAS]) and mapped to a Dashboard service with DashboardDataModels. The Hetzner SQL
engine is ingested via OpenMetadata's built-in MSSQL connector as the table-level lineage
target. Unit tests run against a fixture stub with sockets disabled; the live host is for
integration only.

## Technical Context

- **Language**: Python 3.10 (matches the OpenMetadata 1.13.3 ingestion base image).
- **Core deps**: `openmetadata-ingestion==1.13.3.*` (SDK + entities), `requests` (XMLA over
  HTTP Basic), stdlib `xml.etree` for CSDL + XMLA parsing (lxml is dev-only, for fixture tooling).
- **Test deps**: `pytest`, `pytest-socket` (disable sockets in unit tests), `responses` or a
  local stub server for the fixture stub.
- **Metadata sources** (reader-accessible, spec-defined):
  - tabular → `DISCOVER_CSDL_METADATA` (EntityType→table, Property→column w/ EDM type,
    `bi:Measure`→measure, `Association`→relationship; filter `RowNumber_*`).
  - multidimensional → `MDSCHEMA_CUBES/DIMENSIONS/MEASURES/MEASUREGROUPS/HIERARCHIES/LEVELS`.
  - classification → `DBSCHEMA_CATALOGS.TYPE` (3 tabular / 0 multidimensional).
- **Enum mapping**: a spec-derived table maps DISCOVER integer enums ([MS-SSAS-T] warning).
- **Target**: local Docker, OpenMetadata 1.13.3 + datastore + search; connector image from
  the ingestion base image. SQL Server/SSAS are remote and absent from compose.
- **Trigger**: manual one-shot ingestion for M1.

## Constitution Check

| principle | how the plan complies |
|---|---|
| I No Secret Leakage | creds from `.env`; fixtures scrubbed + leak-check gate in CI; no host/IP/user in logs (structured logging redacts). |
| II Least Privilege | only CSDL + MDSCHEMA + DBSCHEMA (reader) requests; a lint/test asserts zero TMSCHEMA calls. |
| III Offline-First Tests | unit suite uses the stub with `pytest-socket` disabling sockets; no host dependency. |
| IV Discovery-Driven | parsers are written against the recorded fixtures; new assumptions need a fixture first. |
| V Review Gates | one task per commit; `roborev review HEAD` + `wait` between tasks. |

No violations; Complexity Tracking empty.

## Project Structure

### Documentation (this feature)
- spec.md, plan.md, tasks.md (this dir); ../../docs/{spec-brief,discovery-report,references}.md

### Source Code (repository root)
```
src/ssas_om/
  client.py        # XMLA-over-HTTP Basic client (Discover/Execute), fault handling, redaction
  enums.py         # [MS-SSAS]/[MS-SSAS-T] integer-enum → meaning maps
  csdl.py          # [MS-CSDLBI] parser: EntityType/Property/bi:Measure/Association
  mdschema.py      # MDSCHEMA rowset parser (multidimensional)
  classify.py      # DBSCHEMA_CATALOGS.TYPE → model kind
  mapper_tabular.py   # CSDL model → OM database service/table/column/measure
  mapper_cube.py      # MDSCHEMA → OM Dashboard service + DashboardDataModel
  source.py        # OpenMetadata ingestion Source entrypoint (registers the connector)
  redact.py        # shared scrubber (host/IP/user/machine/SID/connstring)
tests/
  unit/            # parser + mapper + client tests, sockets disabled
  fixtures/xmla/   # recorded, scrubbed responses (source of truth)
  conftest.py      # disables sockets; loads fixtures
docker/
  compose.yml      # OpenMetadata 1.13.3 server + db + search + connector image
  ssas-stub/       # serves recorded fixtures for integration-without-host
scripts/probe.py   # discovery/fixture generator (done)
```

## Complexity Tracking

None. Single Python package + Docker; no added architectural complexity beyond the two
mappers required by the two model kinds.
