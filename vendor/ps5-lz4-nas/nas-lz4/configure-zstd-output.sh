#!/bin/bash
# Configure an existing NAS installation. Existing games are not moved.
set -euo pipefail
base="${1:-/volume2/docker/ps5-lz4}"
cd "$base"
cp -p .env .env.before-zstd-output
. ./.env
status="$(docker exec "$CONTAINER" ps5lz4 status)"
if printf '%s\n' "$status" | grep -q '^job: RUNNING'; then
  echo 'A packing job is running. Run this again when it is idle.'
  exit 1
fi
ZSTD_OUTPUT="${ZSTD_OUTPUT:-/volume1/games/ps5zstd}"
mkdir -p "$ZSTD_OUTPUT"
chown "$PUID:$PGID" "$ZSTD_OUTPUT"
cat > docker-compose.zstd.yml <<YAML
services:
  ps5-lz4:
    environment:
      PS5LZ4_ZSTD_OUTPUT: /output-zstd
      PS5LZ4_HOST_ZSTD_OUTPUT: "$ZSTD_OUTPUT"
    volumes:
      - "$ZSTD_OUTPUT:/output-zstd"
  ps5-lz4-ui:
    environment:
      PS5LZ4_ZSTD_OUTPUT: /output-zstd
      PS5LZ4_HOST_ZSTD_OUTPUT: "$ZSTD_OUTPUT"
    volumes:
      - "$ZSTD_OUTPUT:/output-zstd:ro"
YAML
# Compose reads this from .env on subsequent lz4-ps5.sh updates as well.
files="${COMPOSE_FILE:-docker-compose.yml}"
case ":$files:" in *:docker-compose.zstd.yml:*) ;; *) files="$files:docker-compose.zstd.yml" ;; esac
sed -i '/^COMPOSE_FILE=/d; /^ZSTD_OUTPUT=/d' .env
printf '\nZSTD_OUTPUT=%s\nCOMPOSE_FILE=%s\n' "$ZSTD_OUTPUT" "$files" >> .env
export COMPOSE_FILE="$files"
if docker compose version >/dev/null 2>&1; then
  docker compose -p ps5-lz4 config --quiet
  docker compose -p ps5-lz4 pull
  docker compose -p ps5-lz4 up -d
else
  docker-compose -p ps5-lz4 config --quiet
  docker-compose -p ps5-lz4 pull
  docker-compose -p ps5-lz4 up -d
fi
printf 'New Zstd games: %s\nExisting games have not been moved.\n' "$ZSTD_OUTPUT"
