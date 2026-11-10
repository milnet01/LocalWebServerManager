#!/usr/bin/env bash
# LWSM-1021 — runs INSIDE the smoke container; scripts/build-appimage.sh starts
# it with no network and no Python. Proves the AppImage starts.
#
# Usage: _appimage-smoke.sh <AppImage> <expected version>
#
# Two checks:
#   1. `--version` prints the expected version: the bundled Python and the
#      package load.
#   2. A real launch, offscreen, is still running after STAY seconds and has
#      logged its start with no traceback. A missing library or Qt plugin
#      ends the process within a second or two, so surviving means it reached
#      the event loop with its window built.
set -euo pipefail

APPIMAGE="$1"
VERSION="$2"
STAY=15

fail() {
    echo "smoke: FAIL — $*" >&2
    exit 1
}

# No FUSE in a container, so the runtime extracts itself instead of mounting.
export APPIMAGE_EXTRACT_AND_RUN=1
export QT_QPA_PLATFORM=offscreen
export HOME=/tmp/home
export XDG_RUNTIME_DIR=/tmp/runtime
mkdir -p "$HOME"
mkdir -m 0700 "$XDG_RUNTIME_DIR"
LOG="$HOME/.local/state/localwebservermanager/app.log"

got="$("$APPIMAGE" --version)" || fail "--version exited non-zero: $got"
[ "$got" = "lwsm $VERSION" ] || fail "--version printed '$got', expected 'lwsm $VERSION'"
echo "smoke: --version OK ($got)"

"$APPIMAGE" >/tmp/app.out 2>&1 &
pid=$!
for _ in $(seq "$STAY"); do
    sleep 1
    kill -0 "$pid" 2>/dev/null || break
done
if ! kill -0 "$pid" 2>/dev/null; then
    status=0
    wait "$pid" || status=$?
    cat /tmp/app.out >&2
    [ -f "$LOG" ] && cat "$LOG" >&2
    fail "the app exited within ${STAY}s with status $status (output above)"
fi
kill -TERM "$pid"
wait "$pid" || true

[ -f "$LOG" ] || { cat /tmp/app.out >&2; fail "the app wrote no log at $LOG"; }
grep -q "lwsm $VERSION started" "$LOG" || { cat "$LOG" >&2; fail "the log has no start line"; }
if grep -q "Traceback" "$LOG" /tmp/app.out; then
    cat /tmp/app.out "$LOG" >&2
    fail "a traceback was printed (above)"
fi
echo "smoke: launch OK (running after ${STAY}s, start logged, no traceback)"
