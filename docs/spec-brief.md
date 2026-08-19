# SSAS → OpenMetadata connector — design brief

Reconstructed lean after the original brief was lost, and corrected by Step-0 discovery
against the live Hetzner instance (see `discovery-report.md`). Where this brief and the
discovery report disagree, the discovery report wins — it is observed fact.

## Decisions (resolved after discovery)

- **Access model: MDSCHEMA only, read-only `ssas_reader`.** No admin account; the
  connector never uses TMSCHEMA. One MDSCHEMA code path for both model kinds.
- **OpenMetadata version: 1.13.3.** Pin compose + ingestion base image to it.
- **MD cube mapping: a cube-specific shape**, not the tabular database-service shape —
  modelled faithfully to OLAP semantics (cube / measure-groups / dimensions / measures),
  designed now. Tabular remains the database-service shape and the milestone-1 target.
- **Column typing (M1 default, change if you object): coarse buckets** —
  STRING / NUMBER / DATE / BOOLEAN — from `LEVEL_DBTYPE`; full OLE DB mapping later.
- **MSSQL account (default): dedicated read-only SQL login** for engine ingestion,
  parallel to `ssas_reader`; `sa` only as a fallback. Not created yet.

## Purpose

A custom OpenMetadata ingestion connector that extracts metadata from SQL Server
Analysis Services — both a tabular instance and a multidimensional one — exposed as
XMLA-over-HTTP (msmdpump) with Basic auth, and materialises it in a local OpenMetadata
as OpenMetadata entities — the tabular model as a database service (tables/columns), the
multidimensional cube in a cube-specific shape. A second, built-in MSSQL
service ingests the relational source so SSAS→SQL lineage has a target.

## The one architectural decision discovery forced

Use **MDSCHEMA**, not TMSCHEMA, as the metadata interface — for both tabular and
multidimensional models. TMSCHEMA (the tabular-native DMVs) requires an *administrator*
on the AS database; the least-privilege read account faults on every TMSCHEMA rowset.
MDSCHEMA answers for a plain reader and describes both model kinds uniformly. This
replaces the original brief's "probe TMSCHEMA_MODEL and fall back" approach outright.

## Model shape as seen through MDSCHEMA (both kinds, one code path)

| OpenMetadata entity | Tabular (cube is always "Model") | Multidimensional (named cube) |
|---|---|---|
| database / schema | catalog (`DBSCHEMA_CATALOGS`) | catalog |
| table | each `MDSCHEMA_DIMENSIONS` row, `DIMENSION_TYPE=3` | dimensions + measure-group tables |
| column | `MDSCHEMA_HIERARCHIES` (`HIERARCHY_ORIGIN=2`) per dimension | attribute hierarchies / levels |
| column type | `MDSCHEMA_LEVELS.LEVEL_DBTYPE` (OLE DB type code) | same |
| measure | `MDSCHEMA_MEASURES` (`MEASUREGROUP_NAME` links to table) | same |
| measure group | `MDSCHEMA_MEASUREGROUPS` | `MDSCHEMA_MEASUREGROUPS` |
| dim↔measuregroup | `MDSCHEMA_MEASUREGROUP_DIMENSIONS` | same |

Model kind is detected from `DBSCHEMA_CATALOGS.TYPE` (3 = tabular, 0 = multidimensional),
corroborated by `COMPATIBILITY_LEVEL`. No admin-only rowset is needed to classify.

## Components

- `scripts/probe.py` — the discovery tool (done). XMLA over HTTP, Basic auth, writes
  scrubbed fixtures. Reused as the fixture generator for tests.
- `src/…` — the connector: an XMLA client, an MDSCHEMA-driven extractor, and a mapper to
  OpenMetadata entities via the ingestion SDK.
- `docker/compose.yml` — OpenMetadata server + its database + search backend + the
  connector image (from the ingestion base image). No SQL Server / SSAS here; those are
  remote on Hetzner.
- `docker/ssas-stub/` — serves the recorded fixtures so unit tests run with sockets
  disabled and never touch the network.

## Services registered in OpenMetadata

1. Hetzner SQL engine via the built-in **MSSQL** connector, against AdventureWorksDW2022
   — the lineage target; must be ingested before the SSAS-lineage milestone is testable.
2. The SSAS instances via **this** connector.

## Testing

- Unit tests run against `docker/ssas-stub` with **no network** (sockets disabled).
- The Hetzner host is for integration/acceptance only. The suite must never depend on it
  being reachable — the operator IP is allowlisted in the firewall and will change.

## Security

- All credentials, hosts and IPs come from `.env` (gitignored). Never in a committed
  file, fixture, log line or commit message.
- Fixtures are scrubbed of host, IP, username, machine/NetBIOS name, SID and connection
  strings by `probe.py` (verified: zero identifying tokens in the recorded set).

## Milestone-1 definition of done

`docker compose up -d`, then an ingestion run of this connector against the tabular
endpoint produces a database service in the OpenMetadata UI showing the tabular model's
tables and columns. Unit tests pass against the stub with sockets disabled.
