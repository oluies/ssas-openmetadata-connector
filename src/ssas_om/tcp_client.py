"""Read SSAS over the native TCP binding instead of IIS/msmdpump.

Presents exactly the `XmlaClient` interface — `discover`, `execute`, `dmv`, each
returning an `XmlaResult` — so every parser, mapper and the Source itself are
unchanged. The binding is a transport choice, not a modelling one.

Requires the `[tcp]` extra, which pulls in `ssas-xmla-tcp`. That library is
deliberately a separate package: it is a general protocol implementation with one
dependency (`pyspnego`), and pulling the OpenMetadata SDK into it would make it
unusable for anyone else.

The native binding needs no IIS in front of the instance, but it does need the
instance's port to be **pinned** in `msmdsrv.ini` — the named-instance redirector
on TCP 2382 has no public specification and is not used.
"""
from __future__ import annotations

import re

from .client import XmlaResult
from .redact import make_scrubber

# `<CATALOG_NAME>AWTabular</CATALOG_NAME>` -> ("CATALOG_NAME", "AWTabular").
# The HTTP client takes restrictions as a raw XML fragment; the TCP library takes
# a mapping and escapes it, so the fragment is parsed rather than passed through.
_RESTRICTION = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>([^<]*)</\1>")


def _restrictions_to_mapping(restrictions: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _RESTRICTION.finditer(restrictions or "")}


class TcpXmlaClient:
    """An `XmlaClient` work-alike speaking the native binding."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str = "",
        password: str = "",
        auth_mechanism: str = "kerberos",
        service: str = "MSOLAPSvc.3",
        timeout: float = 30.0,
    ) -> None:
        try:
            from ssas_xmla import Credential, connect
        except ImportError as exc:
            raise RuntimeError(
                "transport='tcp' needs the extra: pip install '...[tcp]'"
            ) from exc

        self._scrub = make_scrubber(host=host, user=user or None)
        mech = (auth_mechanism or "kerberos").lower()
        if mech in ("negotiate", "basic"):
            # There is no HTTP Basic on this binding, and negotiate resolves to a
            # ticket mechanism. Say so rather than failing obscurely later.
            mech = "kerberos"
        credential = Credential(mechanism=mech, principal=user or None, service=service)
        # kerberos authenticates from the ambient ticket cache and ignores the
        # password; it is only consulted for ntlm against a standalone server.
        self._session = connect(
            host,
            port,
            credential=credential,
            timeout=timeout,
            password=password or None,
        )

    # -- the XmlaClient surface -------------------------------------------------
    def discover(
        self,
        request_type: str,
        catalog: str | None = None,
        restrictions: str = "",
    ) -> XmlaResult:
        return self._run(
            lambda s: s.discover(
                request_type, _restrictions_to_mapping(restrictions), catalog
            )
        )

    def execute(self, statement: str, catalog: str | None = None) -> XmlaResult:
        return self._run(lambda s: s.execute(statement, catalog))

    def dmv(self, rowset: str, catalog: str | None = None) -> XmlaResult:
        return self.execute(f"SELECT * FROM $SYSTEM.{rowset}", catalog=catalog)

    def close(self) -> None:
        self._session.close()

    # -- internals --------------------------------------------------------------
    def _run(self, call) -> XmlaResult:
        """Map the library's typed errors back onto XmlaResult.

        The Source reads `.ok` and `.fault`, so a refusal has to arrive as a fault
        rather than an exception. Status codes are synthesised to match what the
        HTTP binding would have returned for the same condition, so the callers'
        existing checks keep their meaning.
        """
        from ssas_xmla import (
            AuthenticationError,
            AuthorizationError,
            ConnectionError,
            ServerError,
            SsasError,
        )

        try:
            rows = call(self._session)
        except AuthorizationError as exc:
            return XmlaResult(status=403, text="", fault=self._scrub(str(exc))[:300])
        except AuthenticationError as exc:
            return XmlaResult(status=401, text="", fault=self._scrub(str(exc))[:300])
        except ConnectionError as exc:
            return XmlaResult(status=503, text="", fault=self._scrub(str(exc))[:300])
        except ServerError as exc:
            return XmlaResult(status=200, text="", fault=self._scrub(str(exc))[:300])
        except SsasError as exc:
            return XmlaResult(status=500, text="", fault=self._scrub(str(exc))[:300])
        return XmlaResult(status=200, text=_as_rowset_xml(rows), fault=None)


def _as_rowset_xml(rows) -> str:
    """Re-render a Rowset as the rowset XML the existing parsers expect.

    The TCP library returns parsed rows; `parse_rowset` and the mappers all read
    XML. Re-rendering keeps one parsing path for both bindings rather than
    branching every consumer on which transport produced the data.
    """
    from xml.sax.saxutils import escape

    parts = ['<return><root xmlns="urn:schemas-microsoft-com:xml-analysis:rowset">']
    for row in rows:
        cells = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in row.items())
        parts.append(f"<row>{cells}</row>")
    parts.append("</root></return>")
    return "".join(parts)
