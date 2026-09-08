#!/usr/bin/env bash
# Pins the leak gate's boundary in the tree, not in a throwaway repo.
#
# Every token is ASSEMBLED AT RUNTIME. That is not a workaround: the fixtures for
# this test ARE the shapes the gate blocks, so writing them literally would make
# this file uncommittable — and would be exactly the leak the gate exists to stop.
#
# Both directions matter and both have regressed:
#   too strict: a container image tag blocked every docs commit
#   too loose : a file path with a line number was exempted as an "image ref",
#               so a real address in pasted grep output would have sailed through
set -uo pipefail
HOOK="$(cd "$(dirname "$0")/../.." && pwd)/.githooks/pre-commit"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
cd "$TMP" && git init -q . && git config user.email t@t && git config user.name t

q() { printf '%s.%s.%s.%s' "$1" "$2" "$3" "$4"; }   # dotted quad from octets
LOOPBACK=$(q 127 0 0 1); DOC=$(q 192 0 2 10); DOC2=$(q 203 0 113 4)
REAL=$(q 10 1 2 3); REAL2=$(q 10 20 30 40); REAL3=$(q 10 9 8 7)
REAL4=$(q 198 51 101 7); REAL5=$(q 10 0 0 5)
TAG=$(q 2 0 1 0); VER=$(q 1 2 3 4)
SID="S-1-$(printf '%s-%s-%s-%s-%s' 5 21 1 2 500)"
NETBIOS="WIN-$(printf '%s' AB12CD34)"

fail=0
check() {
  printf '%s\n' "$2" > case.txt
  git add case.txt >/dev/null 2>&1
  if "$HOOK" >/dev/null 2>&1; then got=PASS; else got=BLOCK; fi
  if [ "$got" = "$3" ]; then printf '  ok   %-40s %s\n' "$1" "$got"
  else printf '  FAIL %-40s got=%s want=%s\n' "$1" "$got" "$3"; fail=1; fi
  git rm -q --cached case.txt >/dev/null 2>&1 || true
}

check "image tag, full registry"     "FROM docker.example.io/openmetadata/ingestion:$TAG" PASS
check "image tag, short"             "image: openmetadata/server:$TAG"                    PASS
check "loopback"                     "- \"$LOOPBACK:19200:9200\""                          PASS
check "documentation ranges"         "host $DOC and $DOC2"                                 PASS
check "version string, not an addr"  "released v$VER today"                                PASS
check "bare real address"            "ssas host is $REAL"                                  BLOCK
check "host:addr without a slash"    "somehost:$REAL"                                      BLOCK
check "FILE PATH with line and addr" "src/main.py:$REAL2"                                  BLOCK
check "grep hit in a yaml file"      "config/app.yml:$REAL5"                               BLOCK
check "addr then port"               "$REAL:1433"                                          BLOCK
check "addr inside a url"            "http://$REAL4/olap-tab/msmdpump.dll"                 BLOCK
check "security identifier"          "owner $SID denied"                                   BLOCK
check "netbios machine name"         "machine $NETBIOS responded"                          BLOCK
check "image tag beside a real addr" "FROM openmetadata/ingestion:$TAG on $REAL3"          BLOCK

exit "$fail"
