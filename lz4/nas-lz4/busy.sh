#!/bin/sh
# Watchtower pre-update hook: exit 75 tells Watchtower to skip the update
# while a game is being packed. It tries again on its next poll.
# Runs as the NAS user so it never creates root-owned state files.
run() { if [ -n "${PUID:-}" ] && [ "$(id -u)" = 0 ]; then setpriv --reuid="$PUID" --regid="$PGID" --clear-groups "$@"; else "$@"; fi; }
run ps5lz4 status 2>/dev/null | grep -q '^job: RUNNING' && exit 75
exit 0
