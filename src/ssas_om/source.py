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

from metadata.generated.schema.api.data.createDatabase import CreateDatabaseRequest
from metadata.generated.schema.api.data.createDatabaseSchema import (
    CreateDatabaseSchemaRequest,
)
from metadata.generated.schema.api.data.createTable import CreateTableRequest
from metadata.generated.schema.api.services.createDatabaseService import (
    CreateDatabaseServiceRequest,
)
from metadata.generated.schema.entity.data.table import Column, DataType
from metadata.generated.schema.entity.services.databaseService import (
    DatabaseServiceType,
)
from metadata.generated.schema.metadataIngestion.workflow import (
    Source as WorkflowSource,
)
from metadata.ingestion.api.common import Entity
from metadata.ingestion.api.models import Either
from metadata.ingestion.api.steps import Source
from metadata.ingestion.ometa.ometa_api import OpenMetadata

from .classify import Catalog, list_catalogs
from .client import XmlaClient
from .csdl import parse_csdl
from .mapper_tabular import plan_tabular
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
        # a reader-accessible, non-admin probe
        self.client.discover("DISCOVER_DATASOURCES")

    def _catalogs(self) -> list[Catalog]:
        cats = list_catalogs(self.client)
        if self.catalog_opt:
            cats = [c for c in cats if c.name == self.catalog_opt]
        return cats

    def _iter(self) -> Iterable[Either[Entity]]:
        for cat in self._catalogs():
            if cat.kind != "tabular":
                continue  # milestone-1: tabular database service
            r = self.client.discover(
                "DISCOVER_CSDL_METADATA",
                catalog=cat.name,
                restrictions=f"<CATALOG_NAME>{cat.name}</CATALOG_NAME>",
            )
            if not r.ok:
                continue
            model = parse_csdl(r.text)
            plan, _rels = plan_tabular(model, service=self.service_name, database=cat.name)
            yield from self._emit_database(plan)

    def _emit_database(self, plan: ServicePlan) -> Iterable[Either[Entity]]:
        yield Either(
            right=CreateDatabaseServiceRequest(
                name=plan.service,
                serviceType=DatabaseServiceType.CustomDatabase,
                connection=self.config.serviceConnection.root,
            )
        )
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

    def close(self) -> None:
        return None
