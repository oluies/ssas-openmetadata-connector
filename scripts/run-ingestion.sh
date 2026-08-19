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
RUNTIME=".run-ingestion.yaml"   # gitignored

# JWT for the local ingestion-bot (fetched by the caller into OM_JWT_TOKEN)
: "${OM_JWT_TOKEN:?set OM_JWT_TOKEN (see scripts/om-jwt.sh)}"

envsubst < "$TMPL" > "$RUNTIME"

NET="$(docker network ls --format '{{.Name}}' | grep -E 'app_net$' | head -1)"
docker run --rm --network "$NET" \
  -v "$PWD/src:/opt/connector:ro" \
  -v "$PWD/$RUNTIME:/ingest.yaml:ro" \
  -e PYTHONPATH=/opt/connector \
  docker.getcollate.io/openmetadata/ingestion:1.13.3 \
  metadata ingest -c /ingest.yaml
