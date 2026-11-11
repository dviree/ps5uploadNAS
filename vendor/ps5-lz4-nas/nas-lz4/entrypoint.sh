#!/bin/sh
# Container start (NAS boot, Watchtower update, manual restart): continue an
# unfinished queue as the NAS user, then run the agent that carries out what
# the web page (ps5-lz4-ui) asks for. Jobs also arrive via `docker exec`.
as_user() {
  if [ -n "${PUID:-}" ] && [ -n "${PGID:-}" ] && [ "$(id -u)" = 0 ]; then
    setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"
  else
    "$@"
  fi
}
as_user ps5lz4 start --resume 2>&1 | grep -v '^no unfinished queue' || true
if [ -n "${PUID:-}" ] && [ -n "${PGID:-}" ] && [ "$(id -u)" = 0 ]; then
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups ps5lz4 agent
fi
exec ps5lz4 agent
