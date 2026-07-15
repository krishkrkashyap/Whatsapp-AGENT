#!/usr/bin/env bash
#
# fix-docker.sh — recover a hung Docker Desktop (WSL2) on Windows and bring the
# stack back up. Run from Git Bash.
#
# Symptoms this fixes:
#   - `docker` commands hang or return `500 Internal Server Error` on /_ping
#     (WSL2 backend wedged) — looks like Docker "won't start" for 10+ min.
#   - Containers report healthy but http://localhost:PORT is unreachable
#     (port-proxy bound IPv6-only / stopped forwarding after a WSL restart).
#
# Usage: ./scripts/fix-docker.sh
#
set -euo pipefail

DOCKER_EXE="/c/Program Files/Docker/Docker/Docker Desktop.exe"
COMPOSE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> Stopping Docker Desktop processes"
taskkill //F //IM "Docker Desktop.exe"   >/dev/null 2>&1 || true
taskkill //F //IM "com.docker.backend.exe" >/dev/null 2>&1 || true
taskkill //F //IM "com.docker.build.exe"   >/dev/null 2>&1 || true

echo "==> Shutting down WSL"
wsl --shutdown || true
sleep 3

echo "==> Launching Docker Desktop"
"$DOCKER_EXE" &

echo "==> Waiting for engine (up to 4 min)"
deadline=$((SECONDS + 240))
until docker info >/dev/null 2>&1; do
  if (( SECONDS > deadline )); then
    echo "!! Engine still down after 240s — open Docker Desktop and check manually" >&2
    exit 1
  fi
  sleep 5
done
echo "   engine ready: $(docker version --format 'Server {{.Server.Version}}')"

echo "==> Recreating stack (rebuilds port proxies — fixes unreachable ports)"
cd "$COMPOSE_DIR"
docker compose up -d --force-recreate

echo "==> Verifying host reachability"
sleep 8
for url in http://localhost:8000/health http://localhost:3000 http://localhost:2785/api/health; do
  code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$url" || echo 000)
  echo "   $url -> $code"
done

echo "==> Done. If a port shows 000, run: docker compose up -d --force-recreate <service>"
