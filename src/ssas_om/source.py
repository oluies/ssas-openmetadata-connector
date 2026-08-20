"""OpenMetadata custom Source connector for SSAS (T012).

Wires XMLA client -> classify -> parse (CSDL tabular / MDSCHEMA cube) -> plan ->
OpenMetadata entities. Tabular catalogs are emitted as a database service (the
milestone-1 target); multidimensional catalogs as a dashboard service.

Configured via a `customDatabase`/`customDashboard` source whose `connectionOptions`
carry: host, endpoint, user, password and (optionally) catalog. No admin-gated
(TMSCHEMA) request is ever issued.
"""
from __future__ import annotations

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
from metadata.generated.schema.entity.data.table import Column, DataType, Table
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

from .classify import Catalog, list_catalogs
from .client import XmlaClient
from .csdl import parse_csdl
from .mapper_cube import plan_cube
from .mapper_tabular import plan_tabular
from .mdschema import build_cube_from_client
from .plan import ServicePlan

_FALLBACK_TYPE = DataType.VARCHAR if hasattr(DataType, "VARCHAR") else DataType.STRING


def _om_type(name: str) -> DataType:
    try:
        return DataType[name]
    except KeyError:
        return _FALLBACK_TYPE


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
        self.service_name = config.serviceName
        self.client = XmlaClient(
            url=self.host + self.endpoint,
            user=str(opts["user"]),
            password=str(opts["password"]),
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
        cube = build_cube_from_client(self.client, cat.name)
        if not cube.name:
            return None
        return plan_cube(cube, service=self.service_name, database=cat.name)

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
                    continue
                yield Either(
                    right=AddLineageRequest(
                        edge=EntitiesEdge(
                            fromEntity=EntityReference(id=src.id, type="table"),
                            toEntity=EntityReference(id=dst.id, type="table"),
                        )
                    )
                )

    def close(self) -> None:
        return None
