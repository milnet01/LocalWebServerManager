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
trap cleanup EXIT INT TERM

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
        uv run --quiet lwsm
}

shoot midnight main-window
shoot ledger light-theme
shoot highcontrast-dark high-contrast
shoot midnight filtered -a 'key slash' -a 'type book' -a 'wait 1'
