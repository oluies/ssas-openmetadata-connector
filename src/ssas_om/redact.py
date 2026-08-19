"""Shared scrubber: remove host / IP / user / machine / SID / connection strings.

Used both by the discovery tool (fixture generation) and at runtime, so no identifying
token reaches a fixture, a log line or an error message (constitution principle I).
"""
from __future__ import annotations

import re
from collections.abc import Callable

_IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_SID = re.compile(r"\bS-1-(?:\d+-)+\d+\b")
_CONN = re.compile(
    r"(?i)(Data Source|Provider|Initial Catalog|User ID|Password|Server)=[^;<\"]*"
)


def make_scrubber(
    host: str | None = None,
    user: str | None = None,
    machine: str | None = None,
) -> Callable[[str], str]:
    """Return a function that removes identifying tokens from text.

    `machine` (the Windows/NetBIOS name) may be auto-detected from a DOMAIN\\user
    occurrence when not supplied; see `detect_machine`.
    """
    literals: list[tuple[re.Pattern[str], str]] = []
    for tok, repl in ((host, "HOST"), (machine, "HOST"), (user, "USER")):
        if tok:
            bare = re.sub(r"^https?://", "", tok).strip("/").split("/", 1)[0]
            literals.append((re.compile(re.escape(bare), re.I), f"<{repl}>"))
            if bare != tok:
                literals.append((re.compile(re.escape(tok), re.I), f"<{repl}>"))

    user_adjacent = (
        re.compile(r"([A-Za-z0-9._-]+)\\" + re.escape(user), re.I) if user else None
    )

    def scrub(text: str) -> str:
        if user_adjacent is not None:
            m = user_adjacent.search(text)
            if m and m.group(1):
                text = re.sub(re.escape(m.group(1)), "<HOST>", text, flags=re.I)
        for pat, repl in literals:
            text = pat.sub(repl, text)
        text = _CONN.sub(r"\1=<SCRUBBED>", text)
        text = _IPV4.sub("<IP>", text)
        text = _SID.sub("<SID>", text)
        return text

    return scrub


def detect_machine(text: str, user: str) -> str | None:
    """Extract the Windows/NetBIOS machine name from a DOMAIN\\user occurrence."""
    m = re.search(r"([A-Za-z0-9._-]+)\\" + re.escape(user), text, re.I)
    return m.group(1) if m else None
