# Testing this connector

Six layers, cheapest first. Each one proves something the next cannot, so run them in
order — a failure at layer 5 means something different depending on whether layers 1–4
were green.

| # | Layer | Proves | Needs |
|---|---|---|---|
| 1 | Hermetic unit tests | the parsers and mappers, against recorded fixtures | uv |
| 2 | Lint + types | the tree still matches its own conventions | uv |
| 3 | Leak gate | no host, IP, SID or connection string is committed | bash |
| 4 | Full suite in the SDK image | `SsasSource` against the OpenMetadata SDK | Docker |
| 5 | Binding pre-flight | the instance answers *this* account over *this* transport | the server |
| 6 | Live ingestion | metadata actually lands in OpenMetadata | the server + OM |

Layers 1–4 never touch the network: sockets are blocked and every response comes from a
scrubbed fixture. They pass on a laptop that has never seen an Analysis Services instance,
which is the point — when layer 5 fails, you already know the code is not the suspect.

## Prerequisites (WSL or any Linux)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv manages Python too
exec $SHELL -l
uv --version
docker version                                       # Docker Desktop WSL integration, or docker-ce in the distro
```

Nothing here needs a system Python: uv fetches the interpreter it is asked for.

## 1. Hermetic unit tests

```bash
git clone https://github.com/oluies/ssas-openmetadata-connector.git
cd ssas-openmetadata-connector

uv run --no-project --with pytest --with pytest-socket --with lxml --with requests \
  pytest tests/unit
```

The `SsasSource` tests `importorskip` the OpenMetadata SDK, which is absent here, so they
skip — that is expected, and layer 4 is where they run. Everything else must pass.

CI runs this on Python 3.10, 3.11 and 3.12; to reproduce one of them, add
`--python 3.10`.

## 2. Lint and type-check

```bash
uvx ruff check .        # linter
uvx ruff format --check .
uvx --with requests ty check    # SDK-free core; source.py is the SDK boundary and is excluded
```

## 3. Leak gate

The same script the pre-commit hook runs, over every tracked file rather than the staged
ones, plus its boundary cases (an image tag must pass, a file path carrying a real address
must not):

```bash
LEAK_GATE_FILES_CMD="git ls-files" .githooks/pre-commit
./tests/hooks/test_leak_gate.sh
```

Install the hook locally so a commit cannot skip it: `git config core.hooksPath .githooks`.

## 4. Full suite inside the ingestion image

`source.py` only imports where the OpenMetadata SDK is present, and the SDK's series is
pinned to the runtime image — so the honest place to run it is that image:

```bash
docker run --rm --user root -v "$PWD:/w" -w /w -e PYTHONPATH=/w/src --entrypoint bash \
  docker.getcollate.io/openmetadata/ingestion:2.0.1.0 \
  -c "python -m pip install -q pytest pytest-socket lxml && python -m pytest tests/unit -p no:cacheprovider"
```

`python -m pip`, not `pip`: the image's `pip` is a wrapper that refuses to run as root.
`--user root` is for the bind-mount, and `-p no:cacheprovider` keeps pytest from writing a
cache directory into your working tree as root.

**If `getcollate.io` is unreachable** — a corporate proxy, a locked-down WSL — use the Docker
Hub name instead. It is not a rebuild or a mirror that might drift; both registries serve the
same linux/amd64 digest (`sha256:42a3c912…` for `openmetadata/ingestion:2.0.1.0`,
`sha256:aca874af…` for `openmetadata/ingestion:2.0.2`), which you can check yourself:

```bash
docker manifest inspect openmetadata/ingestion:2.0.2                      | grep -A2 amd64
docker manifest inspect docker.getcollate.io/openmetadata/ingestion:2.0.2 | grep -A2 amd64
```

Swap the registry prefix in the command above, and see the build arg in layer 6.

**Match the image to your OpenMetadata.** This suite passes inside both
`openmetadata/ingestion:2.0.1.0` and `openmetadata/ingestion:2.0.2`, and the SDK requirement is
a range so the image keeps its own SDK — but build on the version you ingest into. Upstream tag
shapes differ, four-part against three, as those two names show. `compose.yml` and CI still
name the 2.0.1 series, so a whole stack brought up from this repo comes up on it unless you
change them, and the Collate registry appears there in four places.

Expect *more* tests than layer 1 — the ones that skipped there now run.

## 5. Prove the binding before you ingest over it

Ingestion failures are ambiguous: an OpenMetadata workflow that dies could be the server,
the account, the transport or the connector. Settle the first three separately.

### Over HTTP (`msmdpump`)

```bash
export SSAS_HOST=https://ssas-host.domain.com SSAS_USER=... SSAS_PASSWORD=...
uv run --no-project --with requests python scripts/probe.py --endpoint tab
```

It writes scrubbed fixtures under `tests/fixtures/xmla/` and prints nothing identifying.

### Over the native TCP binding

This transport is implemented by a separate library,
[`ssas-xmla-tcp`](https://github.com/oluies/ssas-xmla-tcp). Ask it directly, with no
OpenMetadata anywhere in the picture:

```bash
export SSAS_PASSWORD='...'          # from the environment, never argv
uv run --no-project \
  --with "ssas-xmla-tcp @ git+https://github.com/oluies/ssas-xmla-tcp@v0.1.1" \
  python -m ssas_xmla.probe \
    --host ssas-host.domain.com --port 2383 \
    --mechanism ntlm --principal 'DOMAIN\user'
```

Pinned to a tag so the command is reproducible; swap `@v0.1.1` for `@main` only when you
need a fix that is not released yet.

`--mechanism ntlm` is not decoration: the default is `kerberos`, and a padding mechanism
cannot be carried by that frame layout, so the library refuses it rather than sending a
corrupt body. NTLM is the only path exercised end to end.

Every exit code says something different:

| Exit | Meaning |
|---|---|
| 0 | the instance is readable over TCP with no IIS in front of it |
| 2 | never reached a server — host, port or firewall |
| 3 | reached it; identity not established — account, password, or (Kerberos) the SPN |
| 4 | the server declined clear-text XML — a scope change, not a retry |
| 5 | identity fine, the account may not read — permissions |
| 7 | protocol; if it names padding, retry with `--mechanism ntlm` |

The library's own live tests go further — catalogs, a DAX query, and parity against the
HTTP binding:

```bash
git clone https://github.com/oluies/ssas-xmla-tcp.git && cd ssas-xmla-tcp
uv sync --extra dev                  # pytest lives in the dev extra, not the default deps
export SSAS_HOST=ssas-host.domain.com SSAS_PORT=2383
export SSAS_MECHANISM=ntlm SSAS_PRINCIPAL='DOMAIN\user' SSAS_PASSWORD='...'
uv run pytest -m integration
```

`SSAS_PASSWORD` is required for NTLM — it derives its key from the password and reads no
ticket cache. Without it the run skips and says so.

### If WSL cannot reach the instance

WSL2 is NAT'd, so a host reachable only through a VPN on the Windows side often is not
reachable from the distro. Check the transport before blaming anything else:

```bash
nc -vz ssas-host.domain.com 2383
```

If that fails while PowerShell's `Test-NetConnection` succeeds, put
`networkingMode=mirrored` under `[wsl2]` in `%UserProfile%\.wslconfig` and run
`wsl --shutdown`.

## 6. Live ingestion

```bash
cp .env.example .env               # host, user, password, and SSAS_TCP_PORT for the tcp template
docker compose -f docker/compose.yml up -d openmetadata-server
export OM_JWT_TOKEN=...            # ingestion-bot or admin JWT from your OM instance
```

### Over HTTP

```bash
./scripts/run-ingestion.sh config/ingestion-tabular.yaml.tmpl
./scripts/run-ingestion.sh config/ingestion-md.yaml.tmpl
./scripts/run-ingestion.sh config/ingestion-mssql.yaml.tmpl   # the lineage target
```

The script fills the committed template from `.env` into a gitignored runtime copy,
refuses to run if a `${VAR}` the template needs is unset, and deletes the copy on exit.

### Over the native TCP binding

`config/ingestion-tcp.yaml.tmpl` is the same tabular ingestion with `transport: tcp`. It
needs `ssas-xmla-tcp` *in the runtime*, which the stock image does not carry and the dev
bind-mount cannot supply — the mount carries the connector, not its dependencies. Build the
thin image once:

```bash
docker build -t ssas-ingestion:tcp -f docker/Dockerfile.tcp docker/
# a different registry, a different OpenMetadata version, or both:
#   docker build -t ssas-ingestion:tcp -f docker/Dockerfile.tcp docker/ \
#     --build-arg BASE_IMAGE=openmetadata/ingestion:2.0.2
INGESTION_IMAGE=ssas-ingestion:tcp ./scripts/run-ingestion.sh config/ingestion-tcp.yaml.tmpl
```

Connector edits still need no rebuild: `src/` is bind-mounted over `PYTHONPATH` as before.
Only a change to the library pin does.

It ingests into `ssas_tabular_tcp`, a service of its own, so you can compare the two
bindings side by side rather than overwriting one with the other.

### What to check afterwards

In OpenMetadata: the database services appear (`ssas_tabular`, `ssas_md`,
`ssas_tabular_tcp`, `hetzner_mssql`), each model's tables carry typed columns, tabular
tables have a populated **Sample Data** tab, and an SSAS table's lineage links to its SQL
source table.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `transport='tcp' needs the extra` | the runtime lacks `ssas-xmla-tcp` — you ran the stock image, not `ssas-ingestion:tcp` |
| `authMechanism='basic' is not available on transport='tcp'` | the native binding is GSS-API only: use `ntlm`, or `kerberos`/`negotiate` with a ticket |
| `transport='tcp' requires 'port'` | `SSAS_TCP_PORT` is unset; there is no default, and a guessed port presents as a hang |
| `connectionOptions is missing user and password` | `ntlm`/`basic` need both; only `kerberos`/`negotiate` read an ambient identity |
| `could not initialise a ntlm security context` | no password reached the client — NTLM has no ticket cache to fall back on |
| a YAML parse error mentioning the user | `DOMAIN\user` in a double-quoted scalar: `\u` is a YAML escape. The tcp template uses a block scalar for exactly this |
| ingestion hangs, then times out | the *container* cannot reach the instance — it is a hop further out than your shell |
| `found N *app_net networks` | set `OM_NETWORK` to the OpenMetadata compose network |

Credentials live only in `.env` (gitignored) and in the runtime config the script deletes
on exit. Nothing identifying belongs in a fixture, a log line or a commit — the leak gate
in layer 3 is what enforces it.
