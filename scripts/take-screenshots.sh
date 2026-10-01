#!/usr/bin/env bash
# Screenshots for the project page, taken from MADE-UP data only.
#
# The app reads its project list from $XDG_CONFIG_HOME, so pointing that at a
# demo directory is enough to keep the real list out of frame. `demoreel` runs
# the app on a private virtual display, so nothing from the desktop is in
# frame either. Two sample servers are started on unusual ports so some rows
# show as running; both are stopped on exit.
#
# Everything is written under build/demo/ (ignored by git) and docs/screenshots/.
# Nothing goes to /tmp, which is RAM on the author's machine.
set -euo pipefail
cd "$(dirname "$0")/.."

work="$PWD/build/demo"
out="$PWD/docs/screenshots"
config="$work/config/localwebservermanager"
rm -rf "$work"
mkdir -p "$config" "$work/state" "$work/projects" "$out"
# A private runtime directory: the app claims its single-instance socket there,
# and with the real one a running copy of the app is woken instead and the
# screenshot shows an empty display (L7-M4).
mkdir -m 700 "$work/run"

# Five sample projects, each a real directory with a real launcher.
python3 - "$work/projects" "$config/projects.json" <<'EOF'
import json, sys
from pathlib import Path

root, target = Path(sys.argv[1]), Path(sys.argv[2])
samples = [
    ("recipe-box", "Recipe Box", 8601, "shell", ["./start.sh"]),
    ("photo-gallery", "Photo Gallery", 8602, "python", ["python3", "serve.py"]),
    ("budget-planner", "Budget Planner", 8603, "node", ["node", "serve.mjs"]),
    ("book-club", "Book Club", 8604, "shell", ["./start.sh"]),
    ("weather-dashboard", "Weather Dashboard", None, "shell", ["./start.sh"]),
]
records = []
for folder, name, port, kind, argv in samples:
    base = root / folder
    base.mkdir()
    launcher = base / argv[-1].lstrip("./")
    launcher.write_text(f"#!/bin/sh\nexec python3 -m http.server {port or 8605}\n")
    launcher.chmod(0o755)
    records.append({
        "path": str(base), "name": name, "port": port, "kind": kind,
        "argv": argv, "added": "2026-09-25T12:00:00Z",
    })
target.write_text(json.dumps({"schema_version": 1, "projects": records}, indent=2))
EOF

pids=()
cleanup() {
    if [ "${#pids[@]}" -gt 0 ]; then
        kill "${pids[@]}" 2>/dev/null || true
    fi
    rm -rf "$work"
}
trap cleanup EXIT
# Exit rather than return: a returning INT trap let the script carry on into
# the next shot against a deleted $work (L7-L8). EXIT then cleans up once.
trap 'exit 130' INT TERM

# Every sample port must be free, or a row shows someone else's server — or a
# sample server fails to start with its output thrown away (L7-L7).
for port in 8601 8602 8603 8604 8605; do
    if ! python3 -c 'import socket, sys; socket.socket().bind(("127.0.0.1", int(sys.argv[1])))' "$port" 2>/dev/null; then
        printf 'take-screenshots: port %s is in use; free it and run again\n' "$port" >&2
        exit 1
    fi
done

for port in 8602 8604; do
    python3 -m http.server "$port" --bind 127.0.0.1 --directory "$work/projects" \
        >/dev/null 2>&1 &
    pids+=("$!")
done

shoot() {  # shoot <theme> <output name> [demoreel -a steps...]
    local theme="$1" name="$2"
    shift 2
    # The window is sized to the display, or it opens at its default size in
    # one corner and the rest of the picture is black.
    printf '{"schema_version": 1, "theme": "%s", "x": 0, "y": 0, "width": 1280, "height": 800}\n' \
        "$theme" >"$config/settings.json"
    demoreel shot -o "$out/$name.png" -s 1280x800 -a 'wait 3' "$@" -- \
        env -u WAYLAND_DISPLAY QT_QPA_PLATFORM=xcb XDG_SESSION_TYPE=x11 \
        XDG_CONFIG_HOME="$work/config" XDG_STATE_HOME="$work/state" \
        XDG_RUNTIME_DIR="$work/run" \
        uv run --quiet lwsm
}

shoot midnight main-window
shoot ledger light-theme
shoot highcontrast-dark high-contrast
shoot midnight filtered -a 'key slash' -a 'type book' -a 'wait 1'
