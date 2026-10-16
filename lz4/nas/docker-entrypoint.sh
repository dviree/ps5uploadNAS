#!/bin/sh
# Runs the engine as PUID:PGID when they are set, so files it writes on the
# NAS shares stay owned by your NAS user. Without them it runs as root.
set -e

mkdir -p /data/LZ4Compression

if [ -n "$PUID" ] && [ "$PUID" != "0" ]; then
  PGID="${PGID:-$PUID}"
  chown "$PUID:$PGID" /data/LZ4Compression
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups \
    /usr/local/bin/lz4-compression "$@"
fi

exec /usr/local/bin/lz4-compression "$@"
