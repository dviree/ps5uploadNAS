#!/bin/bash
# Installs ps5-lz4 (LZ4 HC packing of PS5 games for APR-EMU) on the NAS.
#
#   sudo -i
#   bash /volume2/docker/ps5-lz4/src/nas-lz4/install.sh --check   # look only
#   nohup bash /volume2/docker/ps5-lz4/src/nas-lz4/install.sh > /volume2/docker/ps5-lz4/install.log 2>&1 &
#
# Paths and user can be changed with environment variables (defaults below).
# Nothing outside BASE and OUTPUT is changed, no other container is touched,
# and the game library is only ever mounted read-only.
set -euo pipefail

LIBRARY="${LIBRARY:-/volume1/games/roms/ps5}"
PS4_LIBRARY="${PS4_LIBRARY:-/volume1/games/roms/ps4}"  # PS4 .pkg files (optional, read-only)
OUTPUT="${OUTPUT:-/volume1/games/ps5-lz4}"
BASE="${BASE:-/volume2/docker/ps5-lz4}"
NAS_USER="${NAS_USER:-sureahad}"
IMAGE="${IMAGE:-ghcr.io/dviree/ps5-lz4:latest}"   # Watchtower keeps it updated
LOCAL_IMAGE="ps5-lz4:local"                       # fallback: built on the NAS
CONTAINER="${CONTAINER:-ps5-lz4}"
LEVEL="${LEVEL:-9}"
FREE_MARGIN_GB="${FREE_MARGIN_GB:-20}"
UI_PORT="${UI_PORT:-5921}"                         # web page: http://<NAS>:$UI_PORT
CATALOG_PORT="${CATALOG_PORT:-9898}"               # package catalog for pkg-receiver's page on the PS5
# yes: the web page can delete original games from the library (the packing
# container then mounts the library writable; packing itself never writes there).
DELETE_ORIGINALS="${DELETE_ORIGINALS:-no}"
LIB_MODE=":ro"; [ "$DELETE_ORIGINALS" = yes ] && LIB_MODE=""
# yes: also run ps5upload (phantomptr/ps5upload, GPL-3.0; its own engine and web
# UI on port 19113, image ghcr.io/phantomptr/ps5upload-engine-webui) with the
# libraries read-only. An existing container named ps5upload is left alone.
PS5UPLOAD="${PS5UPLOAD:-no}"
PS5_IP="${PS5_IP:-}"                                # the PS5's address, for ps5upload
PS5UPLOAD_ALLOW_IP="${PS5UPLOAD_ALLOW_IP:-}"        # who may use it (default: this NAS's /24)

REPO="$(cd "$(dirname "$0")/.." && pwd)"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

say()  { printf '%s %s\n' "[$(date '+%H:%M:%S')]" "$*"; }
ok()   { printf '  [ok]   %s\n' "$*"; }
warn() { printf '  [warn] %s\n' "$*"; }
die()  { printf '  [FAIL] %s\n' "$*"; exit 1; }

# ---------------------------------------------------------------- preflight
say "Preflight (nothing is changed in this step)"
[ "$(id -u)" = 0 ] || die "run as root (sudo -i)"
[ -f "$REPO/nas-lz4/Dockerfile" ] && [ -f "$REPO/tests/host/Makefile" ] || die "run this from the repository checkout ($REPO)"

arch="$(uname -m)"
case "$arch" in
  x86_64|aarch64) ok "architecture $arch" ;;
  *) die "architecture $arch is not supported (x86_64 or aarch64)" ;;
esac
ok "cpus $(nproc), kernel $(uname -r)"

command -v docker >/dev/null || die "docker not found"
docker info >/dev/null 2>&1 || die "docker daemon not reachable"
ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?')"
COMPOSE=""
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE="docker-compose"
fi
if [ -n "$COMPOSE" ]; then ok "compose: $($COMPOSE version 2>/dev/null | head -1)"; else warn "no docker compose; plain docker run will be used"; fi

id "$NAS_USER" >/dev/null 2>&1 || die "user $NAS_USER not found (set NAS_USER=...)"
PUID="$(id -u "$NAS_USER")"; PGID="$(id -g "$NAS_USER")"
ok "files will be owned by $NAS_USER ($PUID:$PGID)"

[ -d "$LIBRARY" ] || die "library $LIBRARY does not exist"
n_exfat=$(find "$LIBRARY/" -maxdepth 4 -iname '*.exfat' -type f 2>/dev/null | wc -l)
n_pfsc=$(find "$LIBRARY/" -maxdepth 4 -iname '*.ffpfsc' -type f 2>/dev/null | wc -l)
n_pfs=$(find "$LIBRARY/" -maxdepth 4 -iname '*.ffpfs' -type f 2>/dev/null | wc -l)
n_vhash=$(find "$LIBRARY/" -maxdepth 4 -iname '*.ffpfsc.vhash' -type f 2>/dev/null | wc -l)
n_dirs=$(find "$LIBRARY/" -maxdepth 4 -name eboot.bin -type f 2>/dev/null | wc -l)
ok "library $LIBRARY: $n_exfat .exfat, $n_pfsc .ffpfsc ($n_vhash with .vhash), $n_pfs .ffpfs, $n_dirs game folders"
PS4_MOUNT=""; PS4_RUN=()
if [ -d "$PS4_LIBRARY" ]; then
  n_pkg=$(find "$PS4_LIBRARY/" -maxdepth 4 -iname '*.pkg' -type f 2>/dev/null | wc -l)
  ok "PS4 packages $PS4_LIBRARY: $n_pkg .pkg"
  PS4_MOUNT="      - \"$PS4_LIBRARY:/library-ps4:ro\""
  PS4_RUN=(-v "$PS4_LIBRARY:/library-ps4:ro" -e PS5LZ4_HOST_PS4_LIBRARY="$PS4_LIBRARY")
else
  warn "no PS4 package folder at $PS4_LIBRARY (set PS4_LIBRARY=... to list .pkg files)"
fi

for v in "$(dirname "$OUTPUT")" "$(dirname "$BASE")"; do
  [ -d "$v" ] || die "$v does not exist"
done
df -h "$(dirname "$OUTPUT")" "$(dirname "$BASE")" | sed 's/^/         /'
if [ "$(df -P "$OUTPUT" 2>/dev/null | awk 'NR==2{print $1}')" = "$(df -P "$BASE" 2>/dev/null | awk 'NR==2{print $1}')" ] && [ -d "$OUTPUT" ] && [ -d "$BASE" ]; then
  warn "OUTPUT and BASE are on the same volume; large temporary data goes to OUTPUT"
fi

if [ -d "$OUTPUT" ]; then
  ok "output $OUTPUT exists ($(find "$OUTPUT" -mindepth 1 -maxdepth 1 | wc -l) entries)"
  if [ -d "$OUTPUT/.work" ] && [ -n "$(ls -A "$OUTPUT/.work" 2>/dev/null)" ]; then
    warn "$OUTPUT/.work already has content (from an earlier script?): $(ls -A "$OUTPUT/.work" | head -5 | tr '\n' ' ')"
    warn "it is left alone; ps5-lz4 uses its own $OUTPUT/.ps5lz4-work"
  fi
else
  ok "output $OUTPUT will be created"
fi

if [ -d "$BASE" ]; then
  ok "base $BASE exists: $(ls -A "$BASE" | tr '\n' ' ')"
else
  ok "base $BASE will be created"
fi

existing="$(docker ps -a --filter "name=^/${CONTAINER}$" --format '{{.Image}} {{.Status}}' || true)"
if [ -n "$existing" ]; then
  project="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$CONTAINER" 2>/dev/null || true)"
  img="${existing%% *}"
  if [ "$img" = "$IMAGE" ] || [ "$project" = "ps5-lz4" ]; then
    ok "container $CONTAINER exists ($existing); it will be recreated"
  else
    die "a different container is already named $CONTAINER ($existing); set CONTAINER=... to use another name"
  fi
else
  ok "no container named $CONTAINER yet"
fi
ui_owner="$(docker ps --format '{{.Names}} {{.Ports}}' | grep -E ":$UI_PORT->" | awk '{print $1}' | grep -vx "$CONTAINER-ui" || true)"
if [ -n "$ui_owner" ]; then
  die "port $UI_PORT is used by $ui_owner; pick another with UI_PORT=..."
elif command -v ss >/dev/null && ss -ltnH 2>/dev/null | awk '{print $4}' | grep -q ":$UI_PORT\$" && ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER-ui"; then
  die "port $UI_PORT is already in use on the NAS; pick another with UI_PORT=..."
fi
ok "web page port $UI_PORT is free"
cat_owner="$(docker ps --format '{{.Names}} {{.Ports}}' | grep -E ":$CATALOG_PORT->" | awk '{print $1}' | grep -vx "$CONTAINER-ui" || true)"
[ -z "$cat_owner" ] || die "port $CATALOG_PORT is used by $cat_owner; pick another with CATALOG_PORT=... (pkg-receiver's page then can't find the catalog by itself)"
ok "other containers: $(docker ps --format '{{.Names}}' | grep -vx "$CONTAINER" | tr '\n' ' ') (not touched)"

if [ "$CHECK_ONLY" = 1 ]; then
  say "Check finished. Nothing was changed. Run without --check to install."
  exit 0
fi

# ---------------------------------------------------------------- install
say "Installing into $BASE"
mkdir -p "$BASE/state" "$BASE/logs" "$BASE/reports" "$OUTPUT"
chown "$PUID:$PGID" "$BASE/state" "$BASE/logs" "$BASE/reports" "$OUTPUT"
install -d -o "$PUID" -g "$PGID" "$OUTPUT/.ps5lz4-work"
# RAR archives in the library are extracted here (the rest of the library
# stays read-only for the containers).
install -d -o "$PUID" -g "$PGID" "$LIBRARY/_extracted"

backup="$BASE/backup-$(date +%Y%m%d-%H%M%S)"
for f in docker-compose.yml .env lz4-ps5.sh Dockerfile; do
  if [ -e "$BASE/$f" ]; then
    mkdir -p "$backup"
    cp -a "$BASE/$f" "$backup/"
    say "backed up existing $f to $backup/"
  fi
done
if [ -e "$BASE/Dockerfile" ]; then
  mv "$BASE/Dockerfile" "$BASE/Dockerfile.old-script"
  say "the earlier script's Dockerfile was renamed to Dockerfile.old-script (not used)"
fi

TZ_NAME="$(cat /etc/timezone 2>/dev/null || readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||' || echo UTC)"
cat > "$BASE/.env" <<EOF
PUID=$PUID
PGID=$PGID
LIBRARY=$LIBRARY
OUTPUT=$OUTPUT
BASE=$BASE
CONTAINER=$CONTAINER
IMAGE=$IMAGE
EOF

cat > "$BASE/docker-compose.yml" <<EOF
# ps5-lz4: generated by nas-lz4/install.sh
services:
  ps5-lz4:
    image: $IMAGE
    container_name: $CONTAINER
    restart: unless-stopped
    init: true
    network_mode: none
    labels:
      # Watchtower updates the published image (false for a local build).
      com.centurylinklabs.watchtower.enable: "false"
      # With lifecycle hooks on, Watchtower waits while a game is packed.
      com.centurylinklabs.watchtower.lifecycle.pre-update: "/usr/local/bin/ps5lz4-busy"
      com.centurylinklabs.watchtower.lifecycle.pre-update-timeout: "1"
    environment:
      PUID: "$PUID"
      PGID: "$PGID"
      PS5LZ4_HOST_LIBRARY: "$LIBRARY"
      PS5LZ4_HOST_OUTPUT: "$OUTPUT"
      PS5LZ4_HOST_STATE: "$BASE/state"
      PS5LZ4_HOST_PS4_LIBRARY: "$PS4_LIBRARY"
      PS5LZ4_LEVEL: "$LEVEL"
      PS5LZ4_FREE_MARGIN_GB: "$FREE_MARGIN_GB"
      PS5LZ4_DELETE_ORIGINALS: "$DELETE_ORIGINALS"
      TZ: "$TZ_NAME"
    volumes:
      - "$LIBRARY:/library$LIB_MODE"
      - "$LIBRARY/_extracted:/library/_extracted"
      - "$OUTPUT:/output"
      - "$BASE/state:/state"
      - "$BASE/logs:/state/logs"
      - "$BASE/reports:/state/reports"

  # Web page. Reads state and leaves requests for the ps5-lz4 agent; it
  # never runs jobs, sees the library and the LZ4 games read-only, and has
  # no Docker socket.
  ps5-lz4-ui:
    image: $IMAGE
    container_name: $CONTAINER-ui
    restart: unless-stopped
    init: true
    user: "$PUID:$PGID"
    command: ["ps5lz4", "ui", "--port", "5921"]
    # Docker's default bridge: no new network (NAS setups with many
    # containers can run out of address pools for new networks).
    network_mode: bridge
    ports:
      - "$UI_PORT:5921"
      - "$CATALOG_PORT:9898"
    labels:
      com.centurylinklabs.watchtower.enable: "false"
    environment:
      PS5LZ4_HOST_LIBRARY: "$LIBRARY"
      PS5LZ4_HOST_OUTPUT: "$OUTPUT"
      PS5LZ4_HOST_STATE: "$BASE/state"
      PS5LZ4_HOST_PS4_LIBRARY: "$PS4_LIBRARY"
      PS5LZ4_LEVEL: "$LEVEL"
      PS5LZ4_DELETE_ORIGINALS: "$DELETE_ORIGINALS"
      TZ: "$TZ_NAME"
    volumes:
      - "$LIBRARY:/library:ro"
$PS4_MOUNT
      - "$OUTPUT:/output:ro"
      - "$BASE/state:/state"
      - "$BASE/logs:/state/logs:ro"
      - "$BASE/reports:/state/reports:ro"
EOF

install -m 755 "$REPO/nas-lz4/lz4-ps5.sh" "$BASE/lz4-ps5.sh"

WATCHTOWER=false
if [ "$IMAGE" != "$LOCAL_IMAGE" ] && say "Pulling $IMAGE" && docker pull -q "$IMAGE" > "$BASE/logs/build.log" 2>&1; then
  ok "image pulled; Watchtower will keep it updated"
  WATCHTOWER=true
else
  [ "$IMAGE" != "$LOCAL_IMAGE" ] && warn "could not pull $IMAGE ($(tail -1 "$BASE/logs/build.log")); building it here instead"
  IMAGE="$LOCAL_IMAGE"
  say "Building $IMAGE (log: $BASE/logs/build.log)"
  if ! docker build -t "$IMAGE" -f "$REPO/nas-lz4/Dockerfile" "$REPO" > "$BASE/logs/build.log" 2>&1; then
    tail -20 "$BASE/logs/build.log"
    die "docker build failed; see $BASE/logs/build.log"
  fi
  ok "image built (Watchtower leaves it alone)"
fi
sed -i "s|^IMAGE=.*|IMAGE=$IMAGE|" "$BASE/.env"
sed -i "s|^    image: .*|    image: $IMAGE|; s|watchtower.enable: \".*\"|watchtower.enable: \"$WATCHTOWER\"|" "$BASE/docker-compose.yml"

say "Starting container $CONTAINER"
if [ -n "$existing" ]; then docker rm -f "$CONTAINER" >/dev/null; fi
docker rm -f "$CONTAINER-ui" >/dev/null 2>&1 || true
if [ -n "$COMPOSE" ]; then
  (cd "$BASE" && $COMPOSE -p ps5-lz4 up -d) || die "compose up failed; see the message above"
else
  docker run -d --name "$CONTAINER" --restart unless-stopped --init --network none \
    --label com.centurylinklabs.watchtower.enable="$WATCHTOWER" \
    --label com.centurylinklabs.watchtower.lifecycle.pre-update=/usr/local/bin/ps5lz4-busy \
    -e PUID="$PUID" -e PGID="$PGID" \
    -e PS5LZ4_HOST_LIBRARY="$LIBRARY" -e PS5LZ4_HOST_OUTPUT="$OUTPUT" \
    -e PS5LZ4_LEVEL="$LEVEL" -e PS5LZ4_FREE_MARGIN_GB="$FREE_MARGIN_GB" -e TZ="$TZ_NAME" \
    -v "$LIBRARY:/library:ro" -v "$LIBRARY/_extracted:/library/_extracted" -v "$OUTPUT:/output" -v "$BASE/state:/state" \
    -v "$BASE/logs:/state/logs" -v "$BASE/reports:/state/reports" \
    "$IMAGE" >/dev/null
  docker run -d --name "$CONTAINER-ui" --restart unless-stopped --init --user "$PUID:$PGID" \
    -p "$UI_PORT:5921" -p "$CATALOG_PORT:9898" --label com.centurylinklabs.watchtower.enable="$WATCHTOWER" \
    -e PS5LZ4_HOST_LIBRARY="$LIBRARY" -e PS5LZ4_HOST_OUTPUT="$OUTPUT" -e PS5LZ4_LEVEL="$LEVEL" -e TZ="$TZ_NAME" \
    -v "$LIBRARY:/library:ro" -v "$OUTPUT:/output:ro" -v "$BASE/state:/state" \
    -v "$BASE/logs:/state/logs:ro" -v "$BASE/reports:/state/reports:ro" ${PS4_RUN[@]+"${PS4_RUN[@]}"} \
    "$IMAGE" ps5lz4 ui --port 5921 >/dev/null
fi
sleep 2
[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" = true ] || die "container did not start"
ok "container running"
NAS_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
ok "web page: http://${NAS_IP:-<NAS IP>}:$UI_PORT"

if [ "$PS5UPLOAD" = yes ]; then
  say "ps5upload"
  if docker ps -a --format '{{.Names}}' | grep -qx ps5upload; then
    ok "a container named ps5upload already exists: left as it is (the web page's PS5 Upload tab shows it)"
  elif [ -z "$PS5_IP" ]; then
    warn "PS5UPLOAD=yes needs PS5_IP=<the PS5's address>; ps5upload was not installed"
  else
    allow="${PS5UPLOAD_ALLOW_IP:-$(echo "${NAS_IP:-192.168.0.1}" | awk -F. '{print $1"."$2"."$3".0/24"}')}"
    install -d -o 65532 -g 65532 "$BASE/ps5upload"
    up_mounts=(-v "$BASE/ps5upload:/data" -v "$LIBRARY:/games:ro")
    roots="/games"
    if [ -d "$PS4_LIBRARY" ]; then up_mounts+=(-v "$PS4_LIBRARY:/pkgs:ro"); roots="/games,/pkgs"; fi
    [ -d "$OUTPUT" ] && { up_mounts+=(-v "$OUTPUT:/lz4:ro"); roots="$roots,/lz4"; }
    docker run -d --name ps5upload --restart unless-stopped --network host \
      --label com.centurylinklabs.watchtower.enable=true \
      -e PS5_ADDR="$PS5_IP" -e PS5UPLOAD_ALLOW_IP="$allow" -e PS5UPLOAD_BROWSE_ROOTS="$roots" \
      "${up_mounts[@]}" ghcr.io/phantomptr/ps5upload-engine-webui:latest >/dev/null \
      && ok "ps5upload: http://${NAS_IP:-<NAS IP>}:19113 (allowed: $allow; no password, keep it on your LAN)" \
      || warn "ps5upload did not start (is port 19113 in use?)"
  fi
fi

say "Self-check"
"$BASE/lz4-ps5.sh" doctor
say "Library"
"$BASE/lz4-ps5.sh" scan

cat <<EOF

Installed. Next steps (as $NAS_USER or root):
  cd $BASE
  ./lz4-ps5.sh scan --check        # which games can use LZ4 packs
  ./lz4-ps5.sh start <# or name>   # ONE game first, runs in the background
  ./lz4-ps5.sh status              # progress
  ./lz4-ps5.sh report              # sizes and savings
EOF
