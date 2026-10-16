#!/bin/sh
# Runs ps5lz4 inside the ps5-lz4 container as your NAS user.
#   ./lz4-ps5.sh scan --check | start <game> | status | report | stop | ...
#   ./lz4-ps5.sh update [--force]   pull the newest image and restart now
#   ./lz4-ps5.sh push <game>        copy a finished LZ4 game to the PS5 over FTP
# stdin is not attached (no -i/-t): ps5lz4 never reads input, and an
# attached stdin would swallow the lines pasted after this command.
DIR="$(cd "$(dirname "$0")" && pwd)"
. "$DIR/.env"

if [ "${1:-}" = update ]; then
  if [ "${2:-}" != --force ] && docker exec -u "$PUID:$PGID" "$CONTAINER" ps5lz4 status 2>/dev/null | grep -q '^job: RUNNING'; then
    echo "a game is being packed; run again when 'status' says idle (or: update --force, the queue resumes after the restart)"
    exit 1
  fi
  old="$(docker inspect -f '{{.Image}}' "$CONTAINER" 2>/dev/null)"
  docker pull "$IMAGE" || { echo "pull failed (DNS or network?); nothing changed"; exit 1; }
  if [ "$(docker image inspect -f '{{.Id}}' "$IMAGE")" = "$old" ]; then
    echo "already up to date"
    exit 0
  fi
  if docker compose version >/dev/null 2>&1; then
    (cd "$DIR" && docker compose -p ps5-lz4 up -d)
  else
    (cd "$DIR" && docker-compose -p ps5-lz4 up -d)
  fi
  sleep 5
  exec docker exec -u "$PUID:$PGID" "$CONTAINER" ps5lz4 --version
fi

# The PS5 transfer needs a network, which only the web page container has.
if [ "${1:-}" = push ]; then
  exec docker exec -u "$PUID:$PGID" "$CONTAINER-ui" ps5lz4 "$@"
fi

exec docker exec -u "$PUID:$PGID" "$CONTAINER" ps5lz4 "$@"
