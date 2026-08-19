#!/usr/bin/env python3
"""XMLA discovery probe for SSAS msmdpump endpoints.

Standalone: `requests` + stdlib only. Sends XMLA (Discover / Execute) over HTTP
with Basic auth, and writes every raw response to
    tests/fixtures/xmla/<endpoint>/<rowset>.xml
after scrubbing hostnames, IPs, usernames, SIDs and connection strings.

Credentials/host come from the environment (load a .env yourself, or `export`).
Nothing identifying is written to a fixture, a log line or stdout.

Usage:
    python scripts/probe.py                 # probe both endpoints, full matrix
    python scripts/probe.py --endpoint tab  # just the tabular endpoint
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("requests is required: pip install requests")

XMLA_NS = "urn:schemas-microsoft-com:xml-analysis"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "xmla"

# Endpoints are identified by a stable, non-identifying label + the msmdpump path.
ENDPOINTS = {
    "tab": "/olap-tab/msmdpump.dll",   # tabular
    "md":  "/olap-md/msmdpump.dll",    # multidimensional
}

# Discover requests keyed by RequestType (no catalog needed).
# Catalog-scoped Discover requests (metadata documents), reader-accessible and
# spec-defined: DISCOVER_CSDL_METADATA -> [MS-CSDLBI] tabular CSDL; XML_METADATA -> ASSL.
DISCOVER_CATALOG_SCOPED = [
    ("DISCOVER_CSDL_METADATA", "<CATALOG_NAME>{cat}</CATALOG_NAME>"),
    ("DISCOVER_XML_METADATA", ""),
]

DISCOVER_ROWSETS = [
    "DISCOVER_DATASOURCES",
    "DBSCHEMA_CATALOGS",
    "DISCOVER_SCHEMA_ROWSETS",
]

# $SYSTEM rowsets queried via Execute with a Catalog. Probed on BOTH modes so we
# learn which actually answer where, rather than assuming.
TMSCHEMA = [
    "TMSCHEMA_MODEL", "TMSCHEMA_TABLES", "TMSCHEMA_COLUMNS", "TMSCHEMA_MEASURES",
    "TMSCHEMA_RELATIONSHIPS", "TMSCHEMA_PARTITIONS", "TMSCHEMA_HIERARCHIES",
    "TMSCHEMA_DATA_SOURCES", "TMSCHEMA_ROLES",
]
MDSCHEMA = [
    "MDSCHEMA_CUBES", "MDSCHEMA_DIMENSIONS", "MDSCHEMA_MEASURES",
    "MDSCHEMA_MEASUREGROUPS", "MDSCHEMA_MEASUREGROUP_DIMENSIONS",
    "MDSCHEMA_HIERARCHIES", "MDSCHEMA_LEVELS", "MDSCHEMA_SETS",
    "MDSCHEMA_PROPERTIES",
]

DISCOVER_TMPL = (
    '<Envelope xmlns="{soap}"><Body>'
    '<Discover xmlns="{xmla}">'
    "<RequestType>{rtype}</RequestType>"
    # restriction injected in probe_one when needed:
    "<Restrictions><RestrictionList/></Restrictions>"
    "<Properties><PropertyList>{props}</PropertyList></Properties>"
    "</Discover></Body></Envelope>"
)
EXECUTE_TMPL = (
    '<Envelope xmlns="{soap}"><Body>'
    '<Execute xmlns="{xmla}">'
    "<Command><Statement>SELECT * FROM $SYSTEM.{rowset}</Statement></Command>"
    "<Properties><PropertyList>{props}</PropertyList></Properties>"
    "</Execute></Body></Envelope>"
)


def _scrubber(host: str, user: str, machine: str | None = None) -> callable:
    """Return a function that removes identifying tokens from response text."""
    patterns: list[tuple[re.Pattern, str]] = []
    # explicit host (with/without scheme) and username
    bare = re.sub(r"^https?://", "", host).strip("/")
    for tok, repl in ((bare, "HOST"), (host, "HOST"), (machine, "HOST"), (user, "USER")):
        if tok:
            patterns.append((re.compile(re.escape(tok), re.I), f"<{repl}>"))
    # IPv4 addresses
    patterns.append((re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "<IP>"))
    # Windows SIDs
    patterns.append((re.compile(r"S-1-(?:\d+-){1,}\d+"), "<SID>"))
    # connection-string fragments (leading keyword up to the next separator)
    patterns.append((re.compile(r"(?i)(Data Source|Provider|Initial Catalog|"
                                r"User ID|Password|Server)=[^;<\"]*", ), r"\1=<SCRUBBED>"))

    user_re = re.compile("([A-Za-z0-9._-]+)" + chr(92) + chr(92) + re.escape(user), re.I)

    def scrub(text: str) -> str:
        # detect the Windows machine/domain name from any DOMAIN\\user occurrence,
        # then scrub that token everywhere (it also appears in datasource/cube names).
        m = user_re.search(text)
        if m and m.group(1):
            text = re.sub(re.escape(m.group(1)), "<HOST>", text, flags=re.I)
        for pat, repl in patterns:
            text = pat.sub(repl, text)
        return text

    return scrub


def _fault(text: str) -> str | None:
    """Return a short fault reason if the response is a SOAP/XMLA fault, else None."""
    m = re.search(r"<faultstring>(.*?)</faultstring>", text, re.S)
    if m:
        return m.group(1).strip()[:200]
    m = re.search(r'Description="([^"]+)"', text)
    if m:
        return m.group(1)[:200]
    return None


def send(session: requests.Session, url: str, body: str, action: str) -> requests.Response:
    return session.post(
        url,
        data=body.encode("utf-8"),
        headers={
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": f'"{XMLA_NS}:{action}"',
        },
        timeout=60,
    )


def probe_one(session, base, label, mode, rowset, scrub, catalog=None, restriction=""):
    """Run one probe; write scrubbed fixture; return (rowset, status)."""
    url = base + ENDPOINTS[label]
    props = f"<Catalog>{catalog}</Catalog>" if catalog else ""
    if mode == "discover":
        body = DISCOVER_TMPL.format(soap=SOAP_NS, xmla=XMLA_NS, rtype=rowset, props=props)
        if restriction:
            body = body.replace(
                "<RestrictionList/>", f"<RestrictionList>{restriction}</RestrictionList>"
            )
        action = "Discover"
    else:
        body = EXECUTE_TMPL.format(soap=SOAP_NS, xmla=XMLA_NS, rowset=rowset, props=props)
        action = "Execute"

    try:
        r = send(session, url, body, action)
    except requests.RequestException:
        return rowset, "transport-error"

    text = r.text
    fault = _fault(text)
    status = f"HTTP {r.status_code}"
    if r.status_code != 200:
        status = f"{status} (fault)" if fault else status
    elif fault:
        status = "fault"
    else:
        # crude row count from the rowset
        rows = text.count("<row>")
        status = f"ok ({rows} rows)"

    out = FIXTURES / label / f"{mode}.{rowset}.xml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(scrub(text), encoding="utf-8")
    return rowset, status


def detect_catalog(session, base, label, scrub) -> str | None:
    """Read DBSCHEMA_CATALOGS and return the first catalog name (unscrubbed, local)."""
    url = base + ENDPOINTS[label]
    body = DISCOVER_TMPL.format(soap=SOAP_NS, xmla=XMLA_NS,
                                rtype="DBSCHEMA_CATALOGS", props="")
    try:
        r = send(session, url, body, "Discover")
    except requests.RequestException:
        return None
    m = re.search(r"<CATALOG_NAME>([^<]+)</CATALOG_NAME>", r.text)
    return m.group(1) if m else None


def detect_machine(session, base, label) -> str | None:
    """Read DISCOVER_DATASOURCES and extract the SSAS server (NetBIOS) name."""
    url = base + ENDPOINTS[label]
    body = DISCOVER_TMPL.format(soap=SOAP_NS, xmla=XMLA_NS,
                                rtype="DISCOVER_DATASOURCES", props="")
    try:
        r = send(session, url, body, "Discover")
    except requests.RequestException:
        return None
    # DataSourceName is "MACHINE\\INSTANCE"; the part before the backslash is the host.
    m = re.search(r"<DataSourceName>([^<\\]+)\\", r.text)
    return m.group(1) if m else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", choices=["tab", "md", "both"], default="both")
    args = ap.parse_args()

    host = os.environ.get("SSAS_HOST")
    user = os.environ.get("SSAS_USER")
    pw = os.environ.get("SSAS_PASSWORD")
    if not all((host, user, pw)):
        sys.exit("set SSAS_HOST / SSAS_USER / SSAS_PASSWORD in the environment")

    session = requests.Session()
    session.auth = (user, pw)
    machine = detect_machine(session, host, "tab") or detect_machine(session, host, "md")
    scrub = _scrubber(host, user, machine)

    labels = ["tab", "md"] if args.endpoint == "both" else [args.endpoint]
    summary: dict[str, list[tuple[str, str]]] = {}

    for label in labels:
        cat = detect_catalog(session, host, label, scrub)
        results: list[tuple[str, str]] = []

        # 1. Discover-by-RequestType rowsets (no catalog)
        for rs in DISCOVER_ROWSETS:
            results.append(probe_one(session, host, label, "discover", rs, scrub))

        # 1b. catalog-scoped metadata documents (CSDL / XML), reader-accessible
        for rs, restr in DISCOVER_CATALOG_SCOPED:
            results.append(probe_one(session, host, label, "discover", rs, scrub,
                                     catalog=cat, restriction=restr.format(cat=cat or "")))

        # 2. TMSCHEMA + MDSCHEMA families via Execute+Catalog on BOTH endpoints
        for rs in TMSCHEMA + MDSCHEMA:
            results.append(probe_one(session, host, label, "execute", rs, scrub, cat))

        summary[label] = results
        # catalog name is model metadata, not a secret, but keep stdout minimal
        print(f"\n=== endpoint '{label}'  catalog={cat!r} ===")
        for rs, st in results:
            print(f"  {rs:<34} {st}")

    print("\nfixtures written under tests/fixtures/xmla/ (scrubbed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
