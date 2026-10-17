#!/bin/sh
# Installs ps5upload with ps5-lz4 on a NAS with Docker, both built from this
# repository, replacing the containers you run now. Run as root over SSH:
#
#   sudo sh nas-install.sh
#
# 1. Reads the settings of your ps5-lz4 and ps5upload containers (folders, PS5
#    address, user), so the new ones see the same ROMs PS5, ROMs PS4 and LZ4
#    folders and keep ps5-lz4's history, database and reports.
# 2. Backs up each old container: its settings (docker inspect), the container
#    as an image (docker save) and its own data (ps5-lz4's state, ps5upload's
#    /data). The game folders are only ever mounted read-only and stay as they
#    are, so they are not copied.
# 3. Asks, then removes the old containers.
# 4. Downloads the code, sets up ps5-lz4 and ps5-lz4-ui with lz4/nas-lz4/
#    install.sh (built here, from this code) and ps5upload with
#    engine/compose.yaml.
#
# DIR, BRANCH and BACKUP_ROOT can be set in the environment.
set -eu

REPO=https://github.com/dviree/ps5uploadNAS
BRANCH=${BRANCH:-lz4-converter}
DIR=${DIR:-/volume1/docker/ps5upload}
BACKUP_ROOT=${BACKUP_ROOT:-/volume1/docker}
OLD="ps5-lz4 ps5-lz4-ui ps5upload"

say() { printf '\n== %s\n' "$*"; }
ask() { # ask "Question" default -> the answer on stdout
  printf '%s [%s]: ' "$1" "$2" >&2
  read -r a </dev/tty || a=
  printf '%s' "${a:-$2}"
}
yes_no() { # yes_no "Question" -> 0 for yes
  printf '%s [j/N]: ' "$1" >&2
  read -r a </dev/tty || a=
  case "$a" in j|J|ja|Ja|y|Y|yes) return 0 ;; *) return 1 ;; esac
}
env_of() { # env_of container NAME -> that variable's value in the container
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$1" 2>/dev/null |
    sed -n "s/^$2=//p" | head -1
}
mount_of() { # mount_of container /destination -> the host folder mounted there
  docker inspect -f '{{range .Mounts}}{{.Destination}}|{{.Source}}{{println}}{{end}}' "$1" 2>/dev/null |
    sed -n "s#^$2|##p" | head -1
}

[ "$(id -u)" = 0 ] || { echo "Kör som root: sudo sh $0"; exit 1; }
command -v docker >/dev/null || { echo "Docker saknas på den här maskinen."; exit 1; }
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif command -v docker-compose >/dev/null; then COMPOSE=docker-compose
else echo "docker compose saknas."; exit 1; fi

say "Containrar på den här maskinen"
docker ps -a --format '{{.Names}}  {{.Image}}  {{.Status}}'

# ── 1. What the old containers use ───────────────────────────────────────────
LIBRARY=$(env_of ps5-lz4 PS5LZ4_HOST_LIBRARY)
PS4_LIBRARY=$(env_of ps5-lz4 PS5LZ4_HOST_PS4_LIBRARY)
OUTPUT=$(env_of ps5-lz4 PS5LZ4_HOST_OUTPUT)
STATE=$(env_of ps5-lz4 PS5LZ4_HOST_STATE)
[ -n "$STATE" ] || STATE=$(mount_of ps5-lz4 /state)
LZ4_UID=$(env_of ps5-lz4 PUID)
PS5_IP=$(env_of ps5upload PS5_ADDR)
ALLOW=$(env_of ps5upload PS5UPLOAD_ALLOW_IP)
UP_DATA=$(mount_of ps5upload /data)

say "Inställningar (Enter tar förslaget inom [ ])"
NAS_IP=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')
LIBRARY=$(ask "Mapp ROMs PS5" "${LIBRARY:-/path/to/roms/ps5}")
PS4_LIBRARY=$(ask "Mapp ROMs PS4" "${PS4_LIBRARY:-/path/to/roms/ps4}")
OUTPUT=$(ask "LZ4-mappen" "${OUTPUT:-/path/to/ps5-lz4}")
BASE=$(ask "ps5-lz4:s mapp (state, loggar, rapporter)" "$(dirname "${STATE:-/volume2/docker/ps5-lz4/state}")")
DEF_USER=
[ -n "$LZ4_UID" ] && DEF_USER=$(getent passwd "$LZ4_UID" | cut -d: -f1 || true)
NAS_USER=$(ask "NAS-användaren som äger filerna" "${DEF_USER:-${SUDO_USER:-sureahad}}")
PS5_IP=$(ask "PS5:ans IP-adress" "${PS5_IP:-192.168.1.50}")
ALLOW=$(ask "Vilka får använda ps5upload (ditt nätverk)" \
  "${ALLOW:-$(printf '%s' "${NAS_IP:-192.168.1.1}" | sed 's/\.[0-9]*$/.0\/24/')}")
UP_DATA=$(ask "ps5uploads data (sparade servrar, historik)" "${UP_DATA:-$BASE/ps5upload}")

# ── 2. Backup ────────────────────────────────────────────────────────────────
BK="$BACKUP_ROOT/backup-$(date +%Y%m%d-%H%M)"
mkdir -p "$BK"
FOUND=
for C in $OLD; do
  docker inspect "$C" >/dev/null 2>&1 || { echo "$C finns inte, hoppar över."; continue; }
  FOUND="$FOUND $C"
  say "Backup av $C"
  docker stop "$C" >/dev/null || true
  docker inspect "$C" > "$BK/$C-inspect.json"
  docker commit "$C" "backup/$C:old" >/dev/null
  docker save "backup/$C:old" -o "$BK/$C-image.tar"
  echo "Sparade inställningar och image."
done
for D in "$BASE/state" "$BASE/reports" "$UP_DATA"; do
  [ -d "$D" ] || continue
  tar -czf "$BK/data$(printf '%s' "$D" | tr '/' '_').tar.gz" -C "$D" .
  echo "Sparade $D ($(du -sh "$D" | cut -f1))."
done
for F in docker-compose.yml .env; do
  if [ -f "$BASE/$F" ]; then cp "$BASE/$F" "$BK/ps5-lz4-$F"; fi
done
say "Backupen ligger i $BK"
ls -lh "$BK"

# ── 3. Remove the old containers ─────────────────────────────────────────────
if [ -n "$FOUND" ]; then
  if yes_no "Backupen är klar. Ta bort de gamla containrarna ($FOUND )?"; then
    # shellcheck disable=SC2086
    docker rm -f $FOUND
  else
    echo "Inget togs bort. De gamla containrarna är stoppade; starta dem med docker start."
    exit 0
  fi
fi

# ── 4. Download the code ─────────────────────────────────────────────────────
say "Hämtar koden till $DIR"
if [ -d "$DIR/.git" ] && command -v git >/dev/null; then
  git -C "$DIR" checkout -- engine/compose.yaml 2>/dev/null || true
  git -C "$DIR" fetch origin "$BRANCH"
  git -C "$DIR" checkout -B "$BRANCH" "origin/$BRANCH"
elif command -v git >/dev/null; then
  git clone -b "$BRANCH" "$REPO.git" "$DIR"
else
  mkdir -p "$DIR"
  URL="https://codeload.github.com/dviree/ps5uploadNAS/tar.gz/refs/heads/$BRANCH"
  if command -v curl >/dev/null; then curl -fsSL "$URL"; else wget -qO- "$URL"; fi |
    tar -xz -C "$DIR" --strip-components=1
fi

# ── 5. ps5-lz4 ───────────────────────────────────────────────────────────────
say "Bygger och startar ps5-lz4 (första gången tar det en stund)"
LIBRARY=$LIBRARY PS4_LIBRARY=$PS4_LIBRARY OUTPUT=$OUTPUT BASE=$BASE NAS_USER=$NAS_USER \
  IMAGE=ps5-lz4:local PS5UPLOAD=no bash "$DIR/lz4/nas-lz4/install.sh"

# ── 6. ps5upload ─────────────────────────────────────────────────────────────
say "Bygger och startar ps5upload (första gången kan det ta 20–40 minuter)"
CF="$DIR/engine/compose.yaml"
mkdir -p "$UP_DATA"
chmod 1777 "$UP_DATA"
sed -i \
  -e "s|PS5_ADDR: \"192.168.1.50\"|PS5_ADDR: \"$PS5_IP\"|" \
  -e "s|PS5UPLOAD_ALLOW_IP: \"192.168.1.0/24\"|PS5UPLOAD_ALLOW_IP: \"$ALLOW\"|" \
  -e "s|- ps5upload-data:/data|- $UP_DATA:/data|" \
  -e "s|- /path/to/roms/ps5:/games:ro|- $LIBRARY:/games:ro|" \
  -e "s|- /path/to/roms/ps4:/pkgs:ro|- $PS4_LIBRARY:/pkgs:ro|" \
  -e "s|- /path/to/ps5-lz4:/lz4:ro|- $OUTPUT:/lz4:ro|" \
  "$CF"
$COMPOSE -p ps5upload -f "$CF" up -d --build

say "Klart"
echo "ps5upload: http://${NAS_IP:-<NAS-IP>}:19113, Convert Games, fliken LZ4."
echo "ps5-lz4:   http://${NAS_IP:-<NAS-IP>}:5921"
echo "Backup:    $BK"
