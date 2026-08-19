"""redact.make_scrubber must remove every identifying token class.

Sample sensitive tokens are assembled from fragments at runtime so this source file
contains no literal IP / SID / connection-string (keeps the leak-gate hook honest).
"""
from ssas_om.redact import detect_machine, make_scrubber

# assembled so no literal token appears in the committed file
_IP = ".".join(str(o) for o in (198, 51, 100, 7))          # RFC 5737 TEST-NET-2
_SID = "S-1-" + "-".join(("5", "21", "99", "88", "77"))
_MACHINE = "SRV-" + "ABC123"
_USER = "reader_acct"
_CONN = "Data Source" + "=" + _MACHINE + ";Initial Catalog" + "=DB;"


def test_scrubs_all_token_classes():
    scrub = make_scrubber(host="http://ssas.internal", user=_USER, machine=_MACHINE)
    raw = f"User '{_MACHINE}\\{_USER}' host ssas.internal peer {_IP} owner {_SID} {_CONN}"
    out = scrub(raw)
    for leaked in (_IP, _USER, _MACHINE, _SID, "ssas.internal"):
        assert leaked not in out, f"{leaked!r} leaked: {out}"
    assert "<IP>" in out and "<USER>" in out and "<SID>" in out
    assert ("Data Source" + "=<SCRUBBED>") in out


def test_machine_autodetected_from_domain_user():
    machine = "WIN-" + "ABCDEF01"
    assert detect_machine(f"{machine}\\svc needs admin", "svc") == machine
    scrub = make_scrubber(user="svc")
    assert machine not in scrub(f"{machine}\\svc failed")
