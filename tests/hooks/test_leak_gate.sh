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
verdict() {  # 1=name 2=want -- stages whatever is in the tree and runs the gate
  git add -A >/dev/null 2>&1
  if "$HOOK" >/dev/null 2>&1; then got=PASS; else got=BLOCK; fi
  if [ "$got" = "$2" ]; then printf '  ok   %-40s %s\n' "$1" "$got"
  else printf '  FAIL %-40s got=%s want=%s\n' "$1" "$got" "$2"; fail=1; fi
  git rm -q --cached -r . >/dev/null 2>&1 || true
  rm -f case.txt case.bin .leakgate-allow
}

check() {
  printf '%s\n' "$2" > case.txt
  verdict "$1" "$3"
}

# Like check(), but the case file is written by a command rather than given as a
# string, so a zero-byte, whitespace-only or NUL-carrying file can be pinned too.
# $4, when given, is written to .leakgate-allow first.
check_file() {
  eval "$2"
  [ -n "${4:-}" ] && printf '%s\n' "$4" > .leakgate-allow
  verdict "$1" "$3"
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d" " -f1
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d" " -f1
  else echo "NO-SHA256-TOOL"; fi
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
check "loopback in a grep hit"       "docs/setup.md:$LOOPBACK"                             PASS
check "doc range in a grep hit"      "compose.yml:$DOC"                                    PASS
check "capitalised filename prefix"  "docker/Dockerfile:$REAL"                             BLOCK
check "extensionless script prefix"  "ci/Makefile:$REAL2"                                  BLOCK
check "uppercase path prefix"        "SRC/MAIN.PY:$REAL3"                                  BLOCK
check "unlisted extension prefix"    "docs/guide.rst:$REAL4"                               BLOCK
check "terraform prefix"             "infra/main.tf:$REAL5"                                BLOCK

# The binary branch. grep -I skips binaries, so without these the gate reports
# CLEAN on files it never read -- how a coverage database carrying home-directory
# paths reached a public repo. All three of its outcomes are pinned here, plus the
# two false refusals that the "is this binary?" test has produced in practice.
check_file "empty file is not binary"     ': > case.txt'            PASS
check_file "blank lines are not binary"   'printf "\n\n\n" > case.txt' PASS
check_file "NUL byte is refused"          'printf "a\000b" > case.bin' BLOCK

# An allowlist entry is a statement about CONTENT, so it must carry the digest.
printf 'a\000b' > case.bin; GOOD=$(sha256_of case.bin); rm -f case.bin
check_file "allowlisted by digest passes" 'printf "a\000b" > case.bin' PASS \
           "$GOOD  case.bin"
check_file "path alone does NOT allowlist" 'printf "a\000b" > case.bin' BLOCK \
           "case.bin"
# The regression the digest exists to stop: a re-captured screenshot replacing an
# already-reviewed one must be refused until someone looks at the new content.
check_file "stale digest re-arms the gate" 'printf "a\000c" > case.bin' BLOCK \
           "$GOOD  case.bin"

exit "$fail"
