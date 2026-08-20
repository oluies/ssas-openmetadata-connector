#!/usr/bin/env bash
# Run the SSAS custom connector ingestion in the OpenMetadata ingestion image.
# Fills the committed template from .env into a gitignored runtime config, refreshes
# the Hetzner firewall to the current egress IP, then runs one ingestion.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.rd/bin:$PATH"

[ -f .env ] || { echo "no .env"; exit 1; }
set -a; . ./.env; set +a

TMPL="${1:-config/ingestion-tabular.yaml.tmpl}"
RUNTIME=".run-ingestion.yaml"   # gitignored; holds substituted secrets
trap 'rm -f "$RUNTIME"' EXIT
umask 077

# require exactly the ${VARS} referenced by the chosen template
for _v in $(grep -oE '\$\{[A-Z_]+\}' "$TMPL" | tr -d '${}' | sort -u); do
  eval ": \"\${$_v:?required by $TMPL}\""
done

envsubst '${SSAS_HOST} ${SSAS_USER} ${SSAS_PASSWORD} ${MSSQL_HOST} ${MSSQL_USER} ${MSSQL_PASSWORD} ${OM_JWT_TOKEN}' < "$TMPL" > "$RUNTIME"

if [ -n "${OM_NETWORK:-}" ]; then
  NET="$OM_NETWORK"
else
  _nets=$(docker network ls --format '{{.Name}}' | grep -E 'app_net$' || true)
  _count=$(printf '%s' "$_nets" | grep -c . || true)
  if [ "$_count" -eq 1 ]; then
    NET="$_nets"
  else
    echo "found $_count *app_net networks; set OM_NETWORK explicitly" >&2
    exit 1
  fi
fi
docker run --rm --network "$NET" --entrypoint metadata \
  -v "$PWD/src:/opt/connector:ro" \
  -v "$PWD/$RUNTIME:/ingest.yaml:ro" \
  -e PYTHONPATH=/opt/connector \
  docker.getcollate.io/openmetadata/ingestion:1.13.3 \
  ingest -c /ingest.yaml
