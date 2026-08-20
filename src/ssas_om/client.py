"""XMLA-over-HTTP client: Discover / Execute with Basic auth.

Never logs request bodies or the Authorization header. Faults are surfaced as data
(not exceptions) with a scrubbed reason. The transport is injectable so tests run
entirely offline against recorded fixtures.

Reference: [MS-SSAS] Authenticate/Discover/Execute over SOAP/XMLA on HTTP.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from .redact import make_scrubber

XMLA_NS = "urn:schemas-microsoft-com:xml-analysis"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"

# transport(url, body, soap_action) -> (status_code, response_text)
Transport = Callable[[str, str, str], "tuple[int, str]"]

_FAULT = re.compile(r"<faultstring>(.*?)</faultstring>", re.S)
_DESC = re.compile(r'Description="([^"]+)"')

_DISCOVER = (
    '<Envelope xmlns="{soap}"><Body><Discover xmlns="{xmla}">'
    "<RequestType>{rtype}</RequestType>"
    "<Restrictions><RestrictionList>{restr}</RestrictionList></Restrictions>"
    "<Properties><PropertyList>{props}</PropertyList></Properties>"
    "</Discover></Body></Envelope>"
)
_EXECUTE = (
    '<Envelope xmlns="{soap}"><Body><Execute xmlns="{xmla}">'
    "<Command><Statement>{stmt}</Statement></Command>"
    "<Properties><PropertyList>{props}</PropertyList></Properties>"
    "</Execute></Body></Envelope>"
)


@dataclass(frozen=True)
class XmlaResult:
    status: int
    text: str
    fault: str | None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.fault is None


def _requests_auth(mechanism: str, user: str, password: str) -> Any:
    """Build a requests auth handler for the SSAS msmdpump IIS endpoint.

    Supported: 'basic' (default). 'kerberos'/'negotiate' and 'ntlm' require optional
    extras (installed via the connector's [kerberos]/[ntlm] extras); Windows SSPI
    Negotiate additionally needs a Windows host or a Kerberos ticket cache.
    """
    mech = (mechanism or "basic").lower()
    if mech == "basic":
        return (user, password)
    if mech in ("kerberos", "negotiate"):
        try:
            from requests_kerberos import OPTIONAL, HTTPKerberosAuth
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "authMechanism='kerberos' needs the extra: pip install '...[kerberos]'"
            ) from exc
        return HTTPKerberosAuth(mutual_authentication=OPTIONAL)
    if mech == "ntlm":
        try:
            from requests_ntlm import HttpNtlmAuth
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "authMechanism='ntlm' needs the extra: pip install '...[ntlm]'"
            ) from exc
        return HttpNtlmAuth(user, password)
    raise ValueError(f"unknown authMechanism: {mechanism!r}")


def _requests_transport(
    url: str, user: str, password: str, auth_mechanism: str = "basic"
) -> Transport:
    import requests  # imported lazily so parser tests need no network stack

    session = requests.Session()
    session.auth = _requests_auth(auth_mechanism, user, password)

    def _send(u: str, body: str, action: str) -> tuple[int, str]:
        r = session.post(
            u,
            data=body.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8",
                     "SOAPAction": f'"{action}"'},
            timeout=60,
        )
        return r.status_code, r.text

    return _send


class XmlaClient:
    def __init__(
        self,
        url: str,
        user: str,
        password: str,
        transport: Transport | None = None,
        auth_mechanism: str = "basic",
    ) -> None:
        self._url = url
        self._scrub = make_scrubber(host=urlsplit(url).hostname or url, user=user)
        self._transport = transport or _requests_transport(
            url, user, password, auth_mechanism
        )

    # -- public API -----------------------------------------------------------------
    def discover(
        self, request_type: str, catalog: str | None = None, restrictions: str = ""
    ) -> XmlaResult:
        props = f"<Catalog>{escape(catalog)}</Catalog>" if catalog else ""
        body = _DISCOVER.format(soap=SOAP_NS, xmla=XMLA_NS, rtype=request_type,
                                restr=restrictions, props=props)
        return self._call(body, f"{XMLA_NS}:Discover")

    def execute(self, statement: str, catalog: str | None = None) -> XmlaResult:
        props = f"<Catalog>{escape(catalog)}</Catalog>" if catalog else ""
        body = _EXECUTE.format(soap=SOAP_NS, xmla=XMLA_NS, stmt=escape(statement), props=props)
        return self._call(body, f"{XMLA_NS}:Execute")

    def dmv(self, rowset: str, catalog: str | None = None) -> XmlaResult:
        """SELECT * FROM $SYSTEM.<rowset> — the reader-accessible metadata path."""
        return self.execute(f"SELECT * FROM $SYSTEM.{rowset}", catalog=catalog)

    # -- internals ------------------------------------------------------------------
    def _call(self, body: str, action: str) -> XmlaResult:
        status, text = self._transport(self._url, body, action)
        return XmlaResult(status=status, text=text, fault=self._fault(text))

    def _fault(self, text: str) -> str | None:
        m = _FAULT.search(text)
        if m is None and ("<soap:Fault" in text or "<Fault" in text or "faultcode" in text):
            # Description= only counts as a fault when a SOAP Fault is present;
            # CSDL bi:Property/bi:Measure annotations also carry Description= legitimately.
            m = _DESC.search(text)
        return self._scrub(m.group(1).strip())[:300] if m else None


def parse_rowset(text: str) -> list[dict[str, str]]:
    """Parse an XMLA rowset response into a list of {column: value} dicts.

    Handles the default `...:rowset` namespace by matching on local element names.
    """
    import xml.etree.ElementTree as ET

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    rows: list[dict[str, str]] = []
    for el in root.iter():
        if local(el.tag) == "row":
            rows.append({local(c.tag): (c.text or "") for c in el})
    return rows
