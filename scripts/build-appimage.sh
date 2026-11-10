#!/usr/bin/env bash
# LWSM-1021 — build the AppImage, then prove it starts on a machine with no
# Python and no Qt.
#
# Usage: scripts/build-appimage.sh
# Writes dist/LocalWebServerManager-<version>-x86_64.AppImage.
#
# Two containers, so the result depends on neither this machine's libraries nor
# its Python:
#   1. Build: python:<.python-version>-slim-bookworm freezes the app with
#      PyInstaller and wraps it with appimagetool (_appimage-build.sh). Debian
#      12's glibc 2.36 is the oldest a user's system may have.
#   2. Smoke: debian:13-slim, with no Python, offline, launches it
#      (_appimage-smoke.sh). An AppImage nobody ran is not a release.
#
# Needs podman or docker, uv, and python3 3.11 or newer (for tomllib). Only the
# build reaches the network.
# The release workflow calls this script; it is the one recipe.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
WORK="$DIST/.appimage-build"

# Pinned by digest; the tag is in the comment because podman refuses both.
# python:3.13.16-slim-bookworm — keep the version equal to .python-version.
BUILD_IMAGE="docker.io/library/python@sha256:73aa5faee130c60da030e105ec971ccf57473fbd22ce73bd6fc9ba99a40b838d"
# debian:13-slim
SMOKE_BASE="docker.io/library/debian@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2"
SMOKE_IMAGE="localhost/lwsm-appimage-smoke:13"

VERSION="$(python3 -c 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])' "$ROOT/pyproject.toml")"
APPIMAGE="LocalWebServerManager-$VERSION-x86_64.AppImage"

if command -v podman >/dev/null 2>&1; then
    RUNNER=podman
elif command -v docker >/dev/null 2>&1; then
    RUNNER=docker
else
    echo "build-appimage: neither podman nor docker is installed" >&2
    exit 1
fi
command -v uv >/dev/null 2>&1 || { echo "build-appimage: uv is not installed" >&2; exit 1; }

echo "== build-appimage: $APPIMAGE (runner: $RUNNER) =="
mkdir -p "$WORK/cache"
rm -f "$DIST/$APPIMAGE"

# The exact runtime closure and PyInstaller, with hashes, from uv.lock. The
# container installs these and nothing else, so the bundle holds what the lock
# says. --locked refuses a lock that no longer matches pyproject.toml, where
# --frozen would export its stale pins.
uv export --locked --no-dev --no-emit-project --extra package \
    --format requirements-txt --output-file "$WORK/requirements.txt" >/dev/null

# label=disable: on an SELinux host a bind mount is unreadable inside the
# container without it. Docker ignores it.
"$RUNNER" run --rm \
    --security-opt label=disable \
    -v "$ROOT":/src:ro \
    -v "$WORK":/work \
    -v "$DIST":/out \
    -e "VERSION=$VERSION" \
    -e "APPIMAGE=$APPIMAGE" \
    "$BUILD_IMAGE" bash /src/scripts/_appimage-build.sh

[ -f "$DIST/$APPIMAGE" ] || { echo "build-appimage: no AppImage was produced" >&2; exit 1; }

# The smoke machine: Debian plus only the libraries every desktop has, which
# the bundle leaves out — GL, tied to the graphics driver; libxkbcommon, which
# must match the host's keyboard data; and one package per library that
# packaging/appimage-excludelist removed from this build.
SMOKE_PACKAGES="libgl1 libegl1 libxkbcommon0 libfontconfig1 libfreetype6"
SMOKE_PACKAGES+=" libharfbuzz0b libstdc++6 libgcc-s1 libx11-6 libx11-xcb1"
SMOKE_PACKAGES+=" libcom-err2 libexpat1 libgpg-error0 zlib1g"
echo "== build-appimage: preparing the smoke machine =="
if ! smoke_build_out="$(printf 'FROM %s\nRUN apt-get update && apt-get install -y --no-install-recommends %s && rm -rf /var/lib/apt/lists/*\n' \
        "$SMOKE_BASE" "$SMOKE_PACKAGES" | "$RUNNER" build -t "$SMOKE_IMAGE" -f - "$WORK" 2>&1)"; then
    printf '%s\n' "$smoke_build_out" >&2
    echo "build-appimage: building the smoke image failed (output above)" >&2
    exit 1
fi

echo "== build-appimage: smoke test (offline, no Python) =="
"$RUNNER" run --rm --network=none \
    --security-opt label=disable \
    -v "$DIST":/artifact:ro \
    -v "$ROOT/scripts":/scripts:ro \
    "$SMOKE_IMAGE" bash /scripts/_appimage-smoke.sh "/artifact/$APPIMAGE" "$VERSION"

echo "== build-appimage: PASS — dist/$APPIMAGE =="
