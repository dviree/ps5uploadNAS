#!/bin/sh
# Installs ps5upload with the LZ4 Compression engine on a NAS with
# Docker, replacing older containers. Run as root over SSH:
#
#   sudo sh nas-install.sh                 # replaces ps5-lz4 and ps5upload
#   sudo sh nas-install.sh ps5-lz4 other   # name the old containers yourself
#
# 1. Backs up each old container: its settings (docker inspect), the container
#    itself as an image (docker save) and the folders and volumes it uses.
# 2. Asks before removing the old containers.
# 3. Downloads the code, fills in engine/compose.yaml from your answers and
#    builds and starts both containers.
#
# DIR, BRANCH and BACKUP_ROOT can be set in the environment.
set -eu

REPO=https://github.com/dviree/ps5uploadNAS
BRANCH=${BRANCH:-lz4-converter}
DIR=${DIR:-/volume1/docker/ps5upload}
BACKUP_ROOT=${BACKUP_ROOT:-/volume1/docker}
OLD=${*:-ps5-lz4 ps5upload}

say() { printf '\n== %s\n' "$*"; }
ask() { # ask "Question" default -> answer on stdout
  printf '%s [%s]: ' "$1" "$2" >&2
  read -r a </dev/tty || a=
  printf '%s' "${a:-$2}"
}
yes_no() { # yes_no "Question" -> 0 for yes
  printf '%s [j/N]: ' "$1" >&2
  read -r a </dev/tty || a=
  case "$a" in j|J|ja|Ja|y|Y|yes) return 0 ;; *) return 1 ;; esac
}

[ "$(id -u)" = 0 ] || { echo "Kör som root: sudo sh $0"; exit 1; }
command -v docker >/dev/null || { echo "Docker saknas på den här maskinen."; exit 1; }
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
elif command -v docker-compose >/dev/null; then COMPOSE=docker-compose
else echo "docker compose saknas."; exit 1; fi

say "Containrar på den här maskinen"
docker ps -a --format '{{.Names}}  {{.Image}}  {{.Status}}'

# ── 1. Backup ────────────────────────────────────────────────────────────────
BK="$BACKUP_ROOT/backup-$(date +%Y%m%d-%H%M)"
mkdir -p "$BK"
FOUND=
LZ4_CONFIG=
OLD_LZ4_DIR=
OLD_EXT_DIR=
for C in $OLD; do
  if ! docker inspect "$C" >/dev/null 2>&1; then
    echo "$C finns inte, hoppar över."
    continue
  fi
  FOUND="$FOUND $C"
  say "Backup av $C"
  docker stop "$C" >/dev/null || true
  docker inspect "$C" > "$BK/$C-inspect.json"
  docker commit "$C" "backup/$C:old" >/dev/null
  docker save "backup/$C:old" -o "$BK/$C-image.tar"
  echo "Sparade inställningar och image."
  docker inspect -f '{{range .Mounts}}{{.Source}}|{{.Destination}}{{"\n"}}{{end}}' "$C" > "$BK/$C-mounts.txt"
  while IFS='|' read -r SRC DST; do
    [ -n "$SRC" ] && [ -e "$SRC" ] || continue
    case "$DST" in
      /data/LZ4Compression) LZ4_CONFIG=$SRC ;;
      /data/homebrew) OLD_LZ4_DIR=$SRC ;;
      /mnt/ext0/homebrew) OLD_EXT_DIR=$SRC ;;
    esac
    SIZE=$(du -sh "$SRC" 2>/dev/null | cut -f1)
    # Game and package libraries are big and stay where they are anyway.
    if [ "$DST" = /data/LZ4Compression ] || [ "$DST" = /data ] ||
      yes_no "Spara även $SRC ($SIZE, i containern $DST)?"; then
      NAME=$(printf '%s' "$SRC" | tr '/' '_')
      tar -czf "$BK/$C-data$NAME.tar.gz" -C "$SRC" .
      echo "Sparade $SRC ($SIZE)."
    else
      echo "Hoppade över $SRC (filerna ligger kvar där de är)."
    fi
  done < "$BK/$C-mounts.txt"
done
say "Backupen ligger i $BK"
ls -lh "$BK"

# ── 2. Remove the old containers ─────────────────────────────────────────────
if [ -n "$FOUND" ]; then
  if yes_no "Backupen är klar. Ta bort de gamla containrarna ($FOUND )?"; then
    # shellcheck disable=SC2086
    docker rm -f $FOUND
  else
    echo "Inget togs bort. De gamla containrarna är stoppade; starta dem med docker start."
    exit 0
  fi
fi

# ── 3. Download the code ─────────────────────────────────────────────────────
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
CF="$DIR/engine/compose.yaml"
cp "$CF" "$CF.orig"

# ── 4. Settings ──────────────────────────────────────────────────────────────
say "Inställningar (Enter tar förslaget inom [ ])"
NAS_IP=$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p')
NET=$(printf '%s' "${NAS_IP:-192.168.1.1}" | sed 's/\.[0-9]*$/.0\/24/')
OWNER=${SUDO_USER:-}
DEF_UID=1026; DEF_GID=100
[ -n "$OWNER" ] && DEF_UID=$(id -u "$OWNER") && DEF_GID=$(id -g "$OWNER")

PS5_IP=$(ask "PS5:ans IP-adress" "192.168.1.50")
ALLOW=$(ask "Vilka får använda appen (ditt nätverk)" "$NET")
# The LZ4 folders default to what the old PS5-LZ4-NAS container used.
ROMS_PS5=$(ask "Mapp ROMs PS5" "${OLD_EXT_DIR:-/volume1/ROMs/PS5}")
ROMS_PS4=$(ask "Mapp ROMs PS4" "/volume1/ROMs/PS4")
LZ4_DIR=$(ask "LZ4-mappen (samma som ps5-lz4 använde)" "${OLD_LZ4_DIR:-/volume1/ROMs/LZ4}")
P_UID=$(ask "PUID (ägare till nya filer)" "$DEF_UID")
P_GID=$(ask "PGID" "$DEF_GID")
if [ -n "$LZ4_CONFIG" ]; then
  LZ4_CONFIG=$(ask "LZ4-inställningar från gamla containern (skriv ny för att börja om)" "$LZ4_CONFIG")
  [ "$LZ4_CONFIG" = ny ] && LZ4_CONFIG=
fi

cp "$CF.orig" "$CF"
sed -i \
  -e "s|PS5_ADDR: \"192.168.1.50\"|PS5_ADDR: \"$PS5_IP\"|" \
  -e "s|PS5UPLOAD_ALLOW_IP: \"192.168.1.0/24\"|PS5UPLOAD_ALLOW_IP: \"$ALLOW\"|" \
  -e "s|- /srv/roms/ps5:|- $ROMS_PS5:|" \
  -e "s|- /srv/roms/ps4:|- $ROMS_PS4:|" \
  -e "s|- /srv/lz4:|- $LZ4_DIR:|" \
  -e "s|- PUID=1000|- PUID=$P_UID|" \
  -e "s|- PGID=1000|- PGID=$P_GID|" \
  -e "s|# user: \"1234:77777\"|user: \"$P_UID:$P_GID\"|" \
  "$CF"
if [ -n "$LZ4_CONFIG" ]; then sed -i "s|- lz4-config:/data/LZ4Compression|- $LZ4_CONFIG:/data/LZ4Compression|" "$CF"; fi
for D in "$ROMS_PS5" "$ROMS_PS4" "$LZ4_DIR"; do mkdir -p "$D"; done

# ── 5. Build and start ───────────────────────────────────────────────────────
say "Bygger och startar (första gången kan det ta 20–40 minuter)"
$COMPOSE -f "$CF" up -d --build

say "Klart"
echo "Öppna http://${NAS_IP:-<NAS-IP>}:19113 och gå till Convert Games."
echo "Backup: $BK"
