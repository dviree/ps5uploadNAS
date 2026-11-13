#!/bin/sh
# Runs ps5lz4 inside the ps5-lz4 container as your NAS user.
#   ./lz4-ps5.sh scan --check | start <game> | status | report | stop | ...
#   ./lz4-ps5.sh update [--force]   pull the newest image and restart now
#   ./lz4-ps5.sh push <game>        copy a finished LZ4 game to the PS5 over FTP
# stdin is not attached (no -i/-t): ps5lz4 never reads input, and an
# attached stdin would swallow the lines pasted after this command.
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/.env"
# Docker Compose reads COMPOSE_FILE from .env when run in DIR, but the wrapper
# must export it too: an unexported shell variable can hide the Zstd override.
[ -z "${COMPOSE_FILE:-}" ] || export COMPOSE_FILE

if [ "${1:-}" = update ]; then
  if [ "${2:-}" != --force ] && docker exec -u "$PUID:$PGID" "$CONTAINER" ps5lz4 status 2>/dev/null | grep -q '^job: RUNNING'; then
    echo "a game is being packed; run again when 'status' says idle (or: update --force, the queue resumes after the restart)"
    exit 1
  fi
  old="$(docker inspect -f '{{.Image}}' "$CONTAINER" 2>/dev/null)"
  docker pull "$IMAGE" || { echo "pull failed (DNS or network?); nothing changed"; exit 1; }
  # Older installations have no /output-zstd bind. Upgrade their Compose
  # configuration before the already-up-to-date shortcut below.
  zstd_added=0
  if ! grep -q 'PS5LZ4_ZSTD_OUTPUT:' "$DIR/docker-compose.yml"; then
    ZSTD_OUTPUT="${ZSTD_OUTPUT:-/volume1/games/ps5zstd}"
    mkdir -p "$ZSTD_OUTPUT" || exit 1
    chown "$PUID:$PGID" "$ZSTD_OUTPUT" || exit 1
    cat > "$DIR/docker-compose.zstd.yml" <<YAML
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
    files="${COMPOSE_FILE:-docker-compose.yml}"
    case ":$files:" in *:docker-compose.zstd.yml:*) ;; *) files="$files:docker-compose.zstd.yml" ;; esac
    if [ "$files" != "${COMPOSE_FILE:-}" ] || ! grep -q '^ZSTD_OUTPUT=' "$DIR/.env"; then
      cp -p "$DIR/.env" "$DIR/.env.before-zstd-output"
      sed -i '/^COMPOSE_FILE=/d; /^ZSTD_OUTPUT=/d' "$DIR/.env"
      printf '\nZSTD_OUTPUT=%s\nCOMPOSE_FILE=%s\n' "$ZSTD_OUTPUT" "$files" >> "$DIR/.env"
      zstd_added=1
    fi
    COMPOSE_FILE="$files"
    export COMPOSE_FILE
  fi
  # The package folder (updates, DLC, backports) for the page's PKG installer
  # tab, on installs made before it: mounted read-only into the page.
  PKG_LIBRARY="${PKG_LIBRARY:-$(dirname "$(dirname "$LIBRARY")")/backport-updates-dlc}"
  if [ -d "$PKG_LIBRARY" ] && ! grep -q ':/library-pkgs:ro"' "$DIR/docker-compose.yml"; then
    sed -i "s|^\(      - \".*:/output:ro\"\)\$|      - \"$PKG_LIBRARY:/library-pkgs:ro\"\n\1|" "$DIR/docker-compose.yml"
    sed -i "/^      PS5LZ4_HOST_PS4_LIBRARY: /a\      PS5LZ4_HOST_PKG_LIBRARY: \"$PKG_LIBRARY\"" "$DIR/docker-compose.yml"
    echo "package folder $PKG_LIBRARY added to the page (read-only)"
    pkg_added=1
  fi
  running=1
  for c in "$CONTAINER" "$CONTAINER-ui"; do
    [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null)" = true ] || running=0
  done
  if [ "$(docker image inspect -f '{{.Id}}' "$IMAGE")" = "$old" ] && [ "$running" = 1 ] && [ -z "${pkg_added:-}" ] && [ "$zstd_added" = 0 ]; then
    echo "already up to date"
    exit 0
  fi
  # A running job is stopped the normal way first (it is resumable) and the
  # recreate waits for it: killing it in the middle of a big disk write can
  # leave the container unkillable ("did not receive an exit event").
  if docker exec -u "$PUID:$PGID" "$CONTAINER" ps5lz4 status 2>/dev/null | grep -q '^job: RUNNING'; then
    echo "stopping the running job first (it resumes after the update)…"
    docker exec -u "$PUID:$PGID" "$CONTAINER" ps5lz4 stop || true
    for i in $(seq 1 60); do
      docker exec -u "$PUID:$PGID" "$CONTAINER" ps5lz4 status 2>/dev/null | grep -q '^job: RUNNING' || break
      sleep 5
    done
  fi
  # A container that was created but never started (a mount that failed, say)
  # is started here too, and its error is shown.
  mkdir -p "$LIBRARY/_extracted" 2>/dev/null || true
  if docker compose version >/dev/null 2>&1; then
    (cd "$DIR" && docker compose -p ps5-lz4 up -d)
  else
    (cd "$DIR" && docker-compose -p ps5-lz4 up -d)
  fi
  sleep 5
  docker exec -u "$PUID:$PGID" "$CONTAINER" ps5lz4 --version
  # Put the image's ampr-emu-ng build into every LZ4 NG and Zstd copy that has an
  # older one (only the runtime file and its index record change; originals and
  # APR-EMU copies are not touched). PS5LZ4_SKIP_RUNTIME_UPGRADE=1 skips it.
  if [ "${PS5LZ4_SKIP_RUNTIME_UPGRADE:-}" != 1 ]; then
    echo "updating ampr-emu-ng in the packed copies…"
    docker exec -u "$PUID:$PGID" "$CONTAINER" ps5lz4 apr --fix | grep -E 'FIXED|upgrade|WRONG|MISSING|NEEDS|need repair|no packed|unchanged' || echo "all copies already had the newest runtime"
  fi
  exit 0
fi

# The PS5 transfer needs a network, which only the web page container has.
if [ "${1:-}" = push ]; then
  exec docker exec -u "$PUID:$PGID" "$CONTAINER-ui" ps5lz4 "$@"
fi

exec docker exec -u "$PUID:$PGID" "$CONTAINER" ps5lz4 "$@"
