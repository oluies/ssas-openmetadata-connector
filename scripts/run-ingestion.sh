#!/usr/bin/env bash
# Run the SSAS custom connector ingestion in the OpenMetadata ingestion image.
# Fills the committed template from .env into a gitignored runtime config, refreshes
# the Hetzner firewall to the current egress IP, then runs one ingestion.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.rd/bin:$PATH"

[ -f .env ] || { echo "no .env"; exit 1; }
set -a; . ./.env; set +a
: "${SSAS_HOST:?}" "${SSAS_USER:?}" "${SSAS_PASSWORD:?}"

TMPL="${1:-config/ingestion-tabular.yaml.tmpl}"
RUNTIME=".run-ingestion.yaml"   # gitignored; holds substituted secrets
trap 'rm -f "$RUNTIME"' EXIT
umask 077

# JWT for the local ingestion-bot (fetched by the caller into OM_JWT_TOKEN)
: "${OM_JWT_TOKEN:?set OM_JWT_TOKEN (see scripts/om-jwt.sh)}"

envsubst '${SSAS_HOST} ${SSAS_USER} ${SSAS_PASSWORD} ${OM_JWT_TOKEN}' < "$TMPL" > "$RUNTIME"

if [ -n "${OM_NETWORK:-}" ]; then
  NET="$OM_NETWORK"
else
  mapfile -t _nets < <(docker network ls --format '{{.Name}}' | grep -E 'app_net$')
  if [ "${#_nets[@]}" -eq 1 ]; then
    NET="${_nets[0]}"
  else
    echo "found ${#_nets[@]} *app_net networks; set OM_NETWORK explicitly" >&2
    exit 1
  fi
fi
docker run --rm --network "$NET" \
  -v "$PWD/src:/opt/connector:ro" \
  -v "$PWD/$RUNTIME:/ingest.yaml:ro" \
  -e PYTHONPATH=/opt/connector \
  docker.getcollate.io/openmetadata/ingestion:1.13.3 \
  metadata ingest -c /ingest.yaml
