#!/usr/bin/env bash
# Deploy the SOP Generator stack on a Proxmox VE host (bare, inside a container/VM).
#
# Usage:
#   curl -fsSL <raw-url-of-this-script> | bash -s -- <deploy-dir>
#   or locally:  bash deploy_pve.sh ./sopgen
#
# Requirements on the Proxmox host: docker + docker compose plugin
set -euo pipefail

DEPLOY_DIR="${1:-/opt/sopgen}"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5-instruct}"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: docker not found on this host. Install it first:"
  echo "  apt install -y docker.io && apt install -y docker-compose-v2"
  exit 1
fi

echo "==> Deploying SOP Generator to $DEPLOY_DIR"
mkdir -p "$DEPLOY_DIR"
cd "$DEPLOY_DIR"

if [ ! -f docker-compose.yml ]; then
  echo "ERROR: $DEPLOY_DIR is empty. Clone/copy the repo contents here first."
  exit 1
fi

echo "==> Building images"
docker compose build sgen
docker compose pull ollama || true

echo "==> Starting stack"
docker compose up -d

echo "==> Waiting for Chrome CDP"
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:9222/json/version >/dev/null; then break; fi
  sleep 2
  [ "$i" = 30 ] && echo "WARNING: CDP did not answer; see 'docker compose logs sgen'"
done

echo "==> Smoke test"
docker compose exec sgen python3 /app/check_smoke.py

echo "==> Pulling Ollama model $OLLAMA_MODEL (first run)"
docker compose exec ollama ollama pull "$OLLAMA_MODEL" || true

echo "==> DONE"
echo "   Control panel:  http://<proxmox-host>:8000"
echo "   Chrome DevTools:http://<proxmox-host>:9222"
echo "   Logs:           docker compose -f $DEPLOY_DIR/docker-compose.yml logs -f sgen"