"""Fixture stub: replays recorded XMLA responses so integration tests need no host.

Routes by the msmdpump path (/olap-tab, /olap-md) and the XMLA request in the body
(RequestType for Discover, `$SYSTEM.<rowset>` or DISCOVER_* for Execute), returning the
matching tests/fixtures/xmla/<endpoint>/<name>.xml. Read-only, localhost, no auth check
(the fixtures are already scrubbed).
"""
from __future__ import annotations

import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "xmla"
ENDPOINTS = {"/olap-tab/msmdpump.dll": "tab", "/olap-md/msmdpump.dll": "md"}

_RTYPE = re.compile(r"<RequestType>([^<]+)</RequestType>")
_DMV = re.compile(r"\$SYSTEM\.([A-Z_]+)")


def resolve(endpoint: str, body: str) -> Path | None:
    m = _RTYPE.search(body)
    if m:
        return FIXTURES / endpoint / f"discover.{m.group(1)}.xml"
    m = _DMV.search(body)
    if m:
        return FIXTURES / endpoint / f"execute.{m.group(1)}.xml"
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # quiet
        pass

    def do_POST(self) -> None:  # noqa: N802
        endpoint = ENDPOINTS.get(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", "replace")
        fixture = resolve(endpoint, body) if endpoint else None
        if fixture and fixture.exists():
            data = fixture.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_error(404, "no fixture for this request")


def serve(host: str = "127.0.0.1", port: int = 8080) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), Handler)
    return httpd


if __name__ == "__main__":
    import sys
    p = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"ssas-stub serving fixtures on 127.0.0.1:{p}")  # noqa: T201
    serve("127.0.0.1", p).serve_forever()
