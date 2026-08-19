"""OpenMetadata ingestion Source entrypoint wiring the pipeline. (T012)

NOT IMPLEMENTED YET — T012. Requires the OpenMetadata SDK; a clear error is raised
if it is missing rather than a bare ModuleNotFoundError.
"""
from __future__ import annotations

try:
    import metadata  # noqa: F401  (openmetadata-ingestion)
except ModuleNotFoundError as exc:  # pragma: no cover - import-time guard
    raise ModuleNotFoundError(
        "The OpenMetadata SDK is required to run the connector Source. "
        "Install it with: pip install 'ssas-om-connector' (openmetadata-ingestion is a "
        "core dependency)."
    ) from exc
