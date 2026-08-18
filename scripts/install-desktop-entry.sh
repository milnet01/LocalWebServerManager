#!/usr/bin/env bash
# Install the desktop entry and icon into the CURRENT USER's home, so the app
# can be launched and pinned like any other application (LWSM-1142).
#
# Nothing here touches system directories and nothing needs root: everything
# lands under $XDG_DATA_HOME (default ~/.local/share), which is the per-user
# half of the same search path /usr/share provides.
#
# Why the Exec line is rewritten rather than shipped ready to use:
# `packaging/*.desktop` carries `Exec=lwsm`, which is correct once the package
# is installed and the console script is on PATH. A development checkout keeps
# that script inside .venv/, which is deliberately NOT on PATH — so an entry
# copied verbatim would appear in the launcher and fail to start. This resolves
# the interpreter that actually exists and writes an absolute path.
#
# Usage:
#   ./scripts/install-desktop-entry.sh              # resolve automatically
#   ./scripts/install-desktop-entry.sh /path/to/lwsm
set -Eeuo pipefail

cd "$(dirname "$0")/.."

app_id="io.github.milnet01.LocalWebServerManager"
data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
apps_dir="$data_home/applications"
icon_dir="$data_home/icons/hicolor/scalable/apps"

# The executable, in order of preference: one named on the command line, this
# checkout's venv, then whatever is on PATH.
if [ $# -ge 1 ]; then
    exec_path="$1"
elif [ -x ".venv/bin/lwsm" ]; then
    exec_path="$PWD/.venv/bin/lwsm"
elif exec_path="$(command -v lwsm)"; then
    :
else
    echo "error: no 'lwsm' executable found." >&2
    echo "       run 'uv sync --extra dev' first, or pass the path as an argument." >&2
    exit 1
fi

if [ ! -x "$exec_path" ]; then
    echo "error: '$exec_path' is not executable." >&2
    exit 1
fi

mkdir -p "$apps_dir" "$icon_dir"
install -m 0644 "packaging/$app_id.svg" "$icon_dir/$app_id.svg"

# Both keys, because they answer different questions: Exec is what runs,
# TryExec is what the launcher checks before offering the entry at all. Leaving
# TryExec as the bare name would hide a perfectly working entry.
sed -e "s|^Exec=.*|Exec=$exec_path|" \
    -e "s|^TryExec=.*|TryExec=$exec_path|" \
    "packaging/$app_id.desktop" > "$apps_dir/$app_id.desktop"
chmod 0644 "$apps_dir/$app_id.desktop"

# Validate what was actually written, never the template — the rewrite above is
# the step that can produce an invalid file.
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$apps_dir/$app_id.desktop"
else
    echo "note: desktop-file-validate not installed; entry written unchecked." >&2
fi

# Cache refreshes. Each is best-effort: a missing tool means the desktop
# environment picks the entry up on its own schedule instead, which is slower
# but not broken, and is not a reason to fail an install that succeeded.
command -v update-desktop-database >/dev/null 2>&1 &&
    update-desktop-database "$apps_dir" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 &&
    gtk-update-icon-cache -q -t -f "$data_home/icons/hicolor" || true
command -v kbuildsycoca6 >/dev/null 2>&1 && kbuildsycoca6 --noincremental >/dev/null 2>&1 || true

echo "Installed:"
echo "  $apps_dir/$app_id.desktop"
echo "  $icon_dir/$app_id.svg"
echo "  Exec=$exec_path"
