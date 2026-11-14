#!/usr/bin/env bash
# LWSM-1021 — runs INSIDE the smoke container; scripts/build-appimage.sh starts
# it with no network and no Python. Proves the AppImage starts.
#
# Usage: _appimage-smoke.sh <AppImage> <expected version>
#
# Four checks:
#   1. `--version` prints the expected version: the bundled Python and the
#      package load.
#   2. A real launch, offscreen, is still running after STAY seconds and has
#      logged its start with no traceback. A missing library or Qt plugin
#      ends the process within a second or two, so surviving means it reached
#      the event loop with its window built. Offscreen only: the xcb and
#      wayland platform plugins are not loaded here, so check 4 covers them.
#   3. A program the app starts gets the launch environment, not the bundle's.
#      A stand-in `systemctl`, which the first scan runs, records what it
#      inherited.
#   4. `ldd` over the bundle's Qt platform plugins finds no missing library.
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

# Check 3's setup. A scan root holding one project makes the first scan run
# `systemctl`; the stand-in on PATH writes its environment and exits.
CHILD_ENV=/tmp/child-env
mkdir -p /tmp/fakebin /tmp/projects/demo "$HOME/.config/localwebservermanager"
printf '#!/bin/sh\nenv > %s\n' "$CHILD_ENV" > /tmp/fakebin/systemctl
chmod +x /tmp/fakebin/systemctl
export PATH="/tmp/fakebin:$PATH"
echo /tmp/projects > "$HOME/.config/localwebservermanager/scan-roots"
echo 'print("demo")' > /tmp/projects/demo/serve.py
# A library path of the user's own, which the child must get back unchanged.
LAUNCH_LIBRARY_PATH=/smoke/launch/lib
export LD_LIBRARY_PATH="$LAUNCH_LIBRARY_PATH"

# Fails on any library a Qt platform plugin (xcb, wayland, ...) cannot find.
# libxkbcommon-x11 and libwayland-cursor are otherwise left to the host by
# design, so the smoke image carries them. $1 is the extracted bundle.
check_platform_plugins() {
    local root=$1 plugins libs missing so
    mapfile -t plugins < <(find "$root" -path '*/platforms/*.so' | sort)
    [ "${#plugins[@]}" -gt 0 ] || fail "no Qt platform plugin found under $root"
    libs="$(find "$root" -name '*.so*' -printf '%h\n' | sort -u | paste -sd:)"
    missing=""
    for so in "${plugins[@]}"; do
        missing+="$(LD_LIBRARY_PATH="$libs" ldd "$so" 2>&1 | grep 'not found' | sed "s|^|${so##*/}: |" || true)"$'\n'
    done
    if [ -n "${missing//$'\n'/}" ]; then
        printf '%s' "$missing" | sed '/^$/d' | sort -u >&2
        fail "a Qt platform plugin lacks a library (above)"
    fi
    echo "smoke: platform plugins OK (${#plugins[@]} checked, no library missing)"
}

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

[ -f "$CHILD_ENV" ] || fail "the app started no systemctl, so no child environment was seen"
leaked="$(grep -E '^(QT_PLUGIN_PATH|QML2_IMPORT_PATH|APPDIR|APPIMAGE|ARGV0|OWD|LD_LIBRARY_PATH_ORIG|_PYI_[A-Z_]*)=' "$CHILD_ENV" || true)"
if [ -n "$leaked" ]; then
    printf '%s\n' "$leaked" >&2
    fail "the bundle's variables reached a child (above)"
fi
child_path="$(sed -n 's/^LD_LIBRARY_PATH=//p' "$CHILD_ENV")"
[ "$child_path" = "$LAUNCH_LIBRARY_PATH" ] ||
    fail "a child got LD_LIBRARY_PATH '$child_path', expected the launch value '$LAUNCH_LIBRARY_PATH'"
echo "smoke: child environment OK (launch library path, no bundle variables)"

EXTRACT=/tmp/extracted
mkdir "$EXTRACT"
(cd "$EXTRACT" && "$APPIMAGE" --appimage-extract >/dev/null) || fail "could not extract the AppImage"
check_platform_plugins "$EXTRACT/squashfs-root"
