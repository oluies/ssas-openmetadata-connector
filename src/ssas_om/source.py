"""OpenMetadata custom Source connector for SSAS (T012).

Wires XMLA client -> classify -> parse (CSDL tabular / MDSCHEMA cube) -> plan ->
OpenMetadata entities. Both tabular catalogs and multidimensional cubes are emitted
as database services (option B — see docs/discovery-report.md).

Configured via a `customDatabase` source whose `connectionOptions` carry: host,
endpoint, user, password and (optionally) catalog. No admin-gated (TMSCHEMA)
request is ever issued.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from xml.sax.saxutils import escape

from metadata.generated.schema.api.data.createDatabase import CreateDatabaseRequest
from metadata.generated.schema.api.data.createDatabaseSchema import (
    CreateDatabaseSchemaRequest,
)
from metadata.generated.schema.api.data.createTable import CreateTableRequest
from metadata.generated.schema.api.lineage.addLineage import AddLineageRequest
from metadata.generated.schema.api.services.createDatabaseService import (
    CreateDatabaseServiceRequest,
)
from metadata.generated.schema.entity.data.table import (
    Column,
    DataType,
    Table,
    TableData,
)
from metadata.generated.schema.entity.services.databaseService import (
    DatabaseServiceType,
)
from metadata.generated.schema.metadataIngestion.workflow import (
    Source as WorkflowSource,
)
from metadata.generated.schema.type.entityLineage import EntitiesEdge
from metadata.generated.schema.type.entityReference import EntityReference
from metadata.ingestion.api.common import Entity
from metadata.ingestion.api.models import Either
from metadata.ingestion.api.steps import Source
from metadata.ingestion.ometa.ometa_api import OpenMetadata
from metadata.utils.logger import ingestion_logger

from .classify import Catalog, list_catalogs
from .client import XmlaClient, parse_rowset
from .csdl import parse_csdl
from .mapper_cube import plan_cubes
from .mapper_tabular import plan_tabular
from .mdschema import build_cubes_from_client
from .plan import ServicePlan

logger = ingestion_logger()

_FALLBACK_TYPE = DataType.VARCHAR if hasattr(DataType, "VARCHAR") else DataType.STRING


def _om_type(name: str) -> DataType:
    try:
        return DataType[name]
    except KeyError:
        return _FALLBACK_TYPE


def _as_bool(value: Any, default: bool) -> bool:
    """connectionOptions arrive as strings; parse a permissive boolean."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


# An XMLA rowset element name encodes non-name characters as `_xHHHH_`
# ([MS-SSAS]/SQL Server XML name escaping) — e.g. `[` -> `_x005B_`, `]` -> `_x005D_`.
_XNAME = re.compile(r"_x([0-9A-Fa-f]{4})_")
# DAX EVALUATE labels columns as `Table[Column]`; keep only the column name.
_DAX_COL = re.compile(r"^.*\[(?P<col>.*)\]$")


def _dax_column_name(key: str) -> str:
    decoded = _XNAME.sub(lambda m: chr(int(m.group(1), 16)), key)
    m = _DAX_COL.match(decoded)
    return m.group("col") if m else decoded


class SsasSource(Source):
    def __init__(self, config: WorkflowSource, metadata: OpenMetadata) -> None:
        super().__init__()
        self.config = config
        self.metadata = metadata
        opts: dict[str, Any] = dict(
            config.serviceConnection.root.config.connectionOptions.root
        )
        self.host = str(opts["host"]).rstrip("/")
        self.endpoint = str(opts["endpoint"])
        self.catalog_opt = opts.get("catalog")
        # optional table-level lineage target (the SQL source ingested separately)
        self.lineage_service = opts.get("lineageService")
        self.lineage_database = opts.get("lineageDatabase")
        self.lineage_schema = opts.get("lineageSchema", "dbo")
        # sample data: on by default; a reader can turn it off or cap the row count
        self.include_sample_data = _as_bool(opts.get("includeSampleData"), True)
        self.sample_data_row_count = _as_int(opts.get("sampleDataRowCount"), 50)
        self.service_name = config.serviceName
        self.client = XmlaClient(
            url=self.host + self.endpoint,
            user=str(opts["user"]),
            password=str(opts["password"]),
            auth_mechanism=str(opts.get("authMechanism", "basic")),
        )

    @classmethod
    def create(
        cls, config_dict: dict, metadata: OpenMetadata, pipeline_name: str | None = None
    ) -> SsasSource:
        return cls(WorkflowSource.model_validate(config_dict), metadata)

    def prepare(self) -> None:  # nothing to pre-fetch
        return None

    def test_connection(self) -> None:
        # a reader-accessible, non-admin probe; a 401/403/fault is NOT healthy
        r = self.client.discover("DISCOVER_DATASOURCES")
        if not r.ok:
            raise ConnectionError(
                f"SSAS connection check failed (HTTP {r.status})"
                + (f": {r.fault}" if r.fault else "")
            )

    def _catalogs(self) -> list[Catalog]:
        cats = list_catalogs(self.client)
        if self.catalog_opt:
            cats = [c for c in cats if c.name == self.catalog_opt]
        return cats

    def _iter(self) -> Iterable[Either[Entity]]:
        emitted_service = False
        for cat in self._catalogs():
            if cat.kind == "tabular":
                plan = self._plan_tabular_catalog(cat)
            elif cat.kind == "multidimensional":
                plan = self._plan_cube_catalog(cat)
            else:
                continue
            if plan is None:
                continue
            if not emitted_service:
                yield self._service_request()
                emitted_service = True
            yield from self._emit_database(plan)
            yield from self._emit_lineage(plan)
            self._emit_sample_data(plan, cat)

    def _plan_tabular_catalog(self, cat: Catalog) -> ServicePlan | None:
        r = self.client.discover(
            "DISCOVER_CSDL_METADATA",
            catalog=cat.name,
            restrictions=f"<CATALOG_NAME>{escape(cat.name)}</CATALOG_NAME>",
        )
        if not r.ok:
            return None
        # relationships are parsed but lineage emission is name-based (see _emit_lineage)
        plan, _rels = plan_tabular(model=parse_csdl(r.text),
                                   service=self.service_name, database=cat.name)
        return plan

    def _plan_cube_catalog(self, cat: Catalog) -> ServicePlan | None:
        cubes = build_cubes_from_client(self.client, cat.name)
        if not cubes:
            return None
        return plan_cubes(cubes, service=self.service_name, database=cat.name)

    def _service_request(self) -> Either[Entity]:
        return Either(
            right=CreateDatabaseServiceRequest(
                name=self.service_name,
                serviceType=DatabaseServiceType.CustomDatabase,
                connection=self.config.serviceConnection.root,
            )
        )

    def _emit_database(self, plan: ServicePlan) -> Iterable[Either[Entity]]:
        db = f"{plan.service}.{plan.database}"
        yield Either(right=CreateDatabaseRequest(name=plan.database, service=plan.service))
        for schema in plan.schemas:
            schema_fqn = f"{db}.{schema.name}"
            yield Either(
                right=CreateDatabaseSchemaRequest(name=schema.name, database=db)
            )
            for table in schema.tables:
                yield Either(
                    right=CreateTableRequest(
                        name=table.name,
                        databaseSchema=schema_fqn,
                        columns=[
                            Column(
                                name=c.name,
                                dataType=_om_type(c.data_type),
                                description=c.description,
                            )
                            for c in table.columns
                        ],
                    )
                )

    def _emit_lineage(self, plan: ServicePlan) -> Iterable[Either[Entity]]:
        """Table-level lineage: SQL source table -> matching SSAS table (by name)."""
        if not (self.lineage_service and self.lineage_database):
            return
        for schema in plan.schemas:
            for table in schema.tables:
                src_fqn = (
                    f"{self.lineage_service}.{self.lineage_database}."
                    f"{self.lineage_schema}.{table.name}"
                )
                dst_fqn = f"{plan.service}.{plan.database}.{schema.name}.{table.name}"
                src = self.metadata.get_by_name(entity=Table, fqn=src_fqn)
                dst = self.metadata.get_by_name(entity=Table, fqn=dst_fqn)
                if src is None or dst is None:
                    missing = src_fqn if src is None else dst_fqn
                    logger.warning("lineage skipped: table not found in catalog: %s", missing)
                    continue
                yield Either(
                    right=AddLineageRequest(
                        edge=EntitiesEdge(
                            fromEntity=EntityReference(id=src.id, type="table"),
                            toEntity=EntityReference(id=dst.id, type="table"),
                        )
                    )
                )

    def _emit_sample_data(self, plan: ServicePlan, cat: Catalog) -> None:
        """Attach a few example rows to each table (reader-side, best-effort).

        Tabular tables are sampled with DAX ``EVALUATE TOPN(n, 'Table')``; the rows are
        posted via the OpenMetadata sample-data API (not the Create* stream), so the
        tables must already be sinked — this runs after ``_emit_database`` yields them.
        Multidimensional cubes are not sampled here (an MDX sampler is a follow-up).
        Controlled by ``includeSampleData`` (default on) and ``sampleDataRowCount``.
        """
        if not self.include_sample_data:
            return
        if cat.kind != "tabular":
            logger.debug("sample data skipped for %s: only tabular is supported", cat.name)
            return
        n = max(1, self.sample_data_row_count)
        for schema in plan.schemas:
            for table in schema.tables:
                fqn = f"{plan.service}.{plan.database}.{schema.name}.{table.name}"
                entity = self.metadata.get_by_name(entity=Table, fqn=fqn)
                if entity is None:
                    logger.warning("sample data skipped: table not found: %s", fqn)
                    continue
                data = self._sample_tabular(cat.name, table.name, n)
                if data is None:
                    continue
                try:
                    self.metadata.ingest_table_sample_data(table=entity, sample_data=data)
                except Exception:  # noqa: BLE001 - never fail a run over sample data
                    logger.warning("sample data ingest failed for %s", fqn, exc_info=True)

    def _sample_tabular(self, catalog: str, table_name: str, n: int) -> TableData | None:
        """Query up to ``n`` rows of a tabular table via DAX and shape TableData."""
        escaped = table_name.replace("'", "''")
        r = self.client.execute(f"EVALUATE TOPN({n}, '{escaped}')", catalog=catalog)
        if not r.ok:
            logger.debug("sample query returned no rows for %s", table_name)
            return None
        rows = parse_rowset(r.text)
        if not rows:
            return None
        keys = [k for k in rows[0] if _dax_column_name(k).lower() != "rownumber"]
        if not keys:
            return None
        columns = [_dax_column_name(k) for k in keys]
        table_rows = [[row.get(k, "") for k in keys] for row in rows]
        return TableData(columns=columns, rows=table_rows)

    def close(self) -> None:
        return None
