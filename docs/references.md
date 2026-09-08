# Normative references

Build the client against the protocol specifications, not blog posts. Where an observed
response disagrees with product documentation, these documents are the authority.

- **[MS-SSAS]** SQL Server Analysis Services Protocol — base protocol: Authenticate,
  Discover, Execute over SOAP/XMLA on TCP/HTTP/HTTPS; rowset column layouts for
  multidimensional models and for tabular at compatibility levels 1100/1103.
  https://learn.microsoft.com/en-us/openspecs/sql_server_protocols/ms-ssas/
- **[MS-SSAS-T]** Analysis Services Tabular Protocol — tabular at compatibility level 1200+:
  TMSCHEMA rowsets, tabular metadata objects, XMLA Create/Alter/Delete/Refresh, TMSL as
  JSON in the XMLA Statement element. **Warning we rely on:** DISCOVER results use *integer
  enumeration values* where TMSL uses strings — the connector MUST map those integers
  itself. https://learn.microsoft.com/en-us/openspecs/sql_server_protocols/ms-ssas-t/
- **[MS-CSDLBI]** Conceptual Schema Definition File Format with BI Annotations — the format
  returned by `DISCOVER_CSDL_METADATA`.
  https://learn.microsoft.com/en-us/openspecs/sql_data_portability/ms-csdlbi/
- **Analysis Services schema rowsets** (product docs landing page routing each rowset family
  to whichever protocol defines it).
  https://learn.microsoft.com/en-us/analysis-services/instances/analysis-services-schema-rowsets

## How these map to our observed, reader-accessible design

| model kind | interface | spec | why |
|---|---|---|---|
| tabular (compat 1600) | `DISCOVER_CSDL_METADATA` | [MS-CSDLBI] | reader-accessible; native tabular shape: EntityType→table, Property→column with **EDM type**, `bi:Measure`→measure, Association→relationship. TMSCHEMA is admin-gated (out of scope, [MS-SSAS-T]). |
| multidimensional | `MDSCHEMA_*` | [MS-SSAS] | reader-accessible; CSDL faults on MD ("model can only be expressed when the client is …"). |

Integer-enum mapping ([MS-SSAS-T] warning) applies to every MDSCHEMA integer we read —
`DIMENSION_TYPE`, `HIERARCHY_ORIGIN`, `MEASURE_AGGREGATOR`, `LEVEL_DBTYPE`, `CUBE`/catalog
`TYPE` — and MUST be mapped from the spec's enumerations, never guessed.

## TCP transport ([MS-SSAS] TCP binding) — not used by the current connector

The connector speaks XMLA over HTTP to the `msmdpump` ISAPI endpoint. [MS-SSAS] also defines
a native TCP binding (a default instance listens on 2383; named instances resolve through
2382), which no pure-Python client implements today — every existing option (ADOMD.NET, the
MSOLAP OLE DB provider, DuckDB's `msolap` extension) is Windows/COM. These are the normative
documents for that binding, recorded so a native transport can be built from the spec rather
than by inspection.

- **[MS-SSAS] Transport** — Authenticate, Discover and Execute over TCP or HTTP/HTTPS;
  message content is clear text XML or binary XML, optionally compressed.
  https://learn.microsoft.com/en-us/openspecs/sql_server_protocols/ms-ssas/cc9c04c8-df61-40aa-b9bf-49d06b3ac888
- **[MS-SSAS] TCP** — DIME record framing: 5-bit VERSION (MUST be 1), MB / ME / CF / TYPE_T
  flags, then OPTIONS / ID / TYPE / DATA lengths, each padded to a 4-byte boundary. **The
  fact that makes a pure-Python client tractable:** binary XML and compression are OPTIONAL
  and negotiated through the first OPTIONS byte (NEGO, REQ_SX, REQ_XPRESS, RESP_SX,
  RESP_XPRESS), so a client MAY negotiate `text/xml` (TYPE_LENGTH 8) and skip [MS-BINXML]
  and XPRESS compression entirely.
  https://learn.microsoft.com/en-us/openspecs/sql_server_protocols/ms-ssas/f172a52f-f69e-4051-8b3a-627433e978fb
- **[MS-SSAS] Authentication and Encryption** — an authenticated or encrypted TCP connection
  MUST use GSS-API [RFC4178]. Security tokens are carried *inside SOAP* — `Authenticate`
  (AuthenticateSoapIn) and `AuthenticateResponse` (AuthenticateSoapOut) — exchanged until
  GSS-API reports completion or error, after which each side asks GSS-API whether encryption
  or hashing is on for the connection. SSPI is the default for TCP, covering NTLM, Kerberos
  or Anonymous. None of this applies over HTTP/HTTPS, where HTTPS provides encryption.
  https://learn.microsoft.com/en-us/openspecs/sql_server_protocols/ms-ssas/be84959b-ec40-4f5a-b18b-b271b0901668
- **[MS-BINXML]** Binary XML — needed only if `application/sx` is negotiated; avoidable per
  the note above. https://learn.microsoft.com/en-us/openspecs/sql_server_protocols/ms-binxml/
- **[DIME]** Direct Internet Message Encapsulation — the framing [MS-SSAS] normatively
  requires on TCP. https://go.microsoft.com/fwlink/?LinkId=89847
- **[RFC4178]** SPNEGO — the GSS-API negotiation mechanism the TCP handshake uses.
  https://www.rfc-editor.org/rfc/rfc4178

A transport is already injectable (`XmlaClient(transport=...)`, `src/ssas_om/client.py`), so
a TCP implementation would slot in beside `_requests_transport` with the CSDL and MDSCHEMA
parsers, the mappers and the Source unchanged. One caveat: `Transport` is typed to return an
HTTP status code, so that alias needs reshaping before a non-HTTP transport can satisfy it.
