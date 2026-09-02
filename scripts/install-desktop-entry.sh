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
#
# They are quoted DIFFERENTLY, and that is the spec rather than an oversight.
# Exec is a command line, so it is parsed and must be quoted; TryExec is a
# path, compared against the filesystem, and quoting it would make the launcher
# look for a file whose name begins with a quote.
#
# TWO escaping layers, applied in this order, because the spec has two: the
# quoting rule reserves `"`, backtick, `$` and backslash inside a quoted
# argument, and the string-value rule then escapes the backslashes that
# produced. So a literal backslash ends up as FOUR, which the spec states
# outright and `desktop-file-validate` enforces — a single pass writes
# `Exec="...back\\slash..."` and the validator rejects it as an unclosed
# quote.
#
# The path is the INPUT to this sed, never its replacement, which is the whole
# point (LWSM-1209).
exec_quoted=$(printf '%s' "$exec_path" | sed -e 's/[\\"`$]/\\&/g' -e 's/\\/\\\\/g')

# awk via ENVIRON, not `sed s|...|$exec_path|` and not `awk -v`. A path is data
# and both of those treat it as syntax: in a sed replacement `&` expands to the
# whole match and `|` closes the s-command, so a checkout under `a&b` wrote
# `Exec=/home/u/aExec=lwsmb/lwsm` and one under `pipe|x` failed outright; `awk
# -v` would process backslash escapes in the value. ENVIRON does neither.
LWSM_EXEC_LINE="Exec=\"$exec_quoted\"" \
LWSM_TRYEXEC_LINE="TryExec=$exec_path" \
    awk '
        /^Exec=/     { print ENVIRON["LWSM_EXEC_LINE"];    next }
        /^TryExec=/  { print ENVIRON["LWSM_TRYEXEC_LINE"]; next }
                     { print }
    ' "packaging/$app_id.desktop" > "$apps_dir/$app_id.desktop"
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
#
# `gtk-update-icon-cache` is deliberately NOT run here, and this is the one
# comment in this file worth reading before "improving" it.
#
# $data_home/icons/hicolor is SHARED: every application that installs a
# per-user icon writes into it. It normally has no `index.theme` and no
# `icon-theme.cache`, and icon lookup then reads the directory directly, which
# works for everyone. Generating a cache there does not merely speed that up —
# it CHANGES the lookup, because once a cache exists it is treated as
# authoritative for that directory and anything the cache does not list stops
# resolving. So a cache built by this installer silently governs every OTHER
# application's icons too.
#
# Measured on 2026-08-18, not theorised: running it once here produced a 1,932
# byte cache over a tree holding 90 icons, and about seventeen of the user's
# pinned launchers went blank until the cache was deleted and plasmashell
# restarted. Installing one application's icon must not be able to do that.
#
# Nothing is lost by omitting it: with no cache present the icon resolves from
# the file, which is verified by the entry working.
#
# Written as `if` blocks rather than `A && B || C`: shellcheck 0.9 (which is
# what the CI runner's apt ships) reports SC2015 on that form and 0.11 does
# not, so the two lines below were green locally and red on GitHub for every
# push on 2026-08-18. The tool versions are pinned now (scripts/ci-tools.env),
# but the explicit form is clearer anyway and cannot re-open the argument.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$apps_dir" || true
fi
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental >/dev/null 2>&1 || true
fi

echo "Installed:"
echo "  $apps_dir/$app_id.desktop"
echo "  $icon_dir/$app_id.svg"
echo "  Exec=$exec_path"
