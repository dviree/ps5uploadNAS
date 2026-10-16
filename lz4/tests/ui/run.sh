#!/bin/sh
# Runs the web UI checks: ./tests/ui/run.sh [python] [screenshot dir]
# Needs Pillow and Playwright (pip install pillow playwright && playwright install webkit).
set -e
here=$(cd "$(dirname "$0")" && pwd)
py=${1:-python3}
out=${2:-$here/out}
port=17610
mkdir -p "$out"
"$py" "$here/stub_server.py" "$here/../../assets" "$port" > "$out/server.log" 2>&1 &
server=$!
trap 'kill $server 2>/dev/null' EXIT
sleep 1.5
"$py" "$here/test_ui.py" "http://127.0.0.1:$port" "$out"
