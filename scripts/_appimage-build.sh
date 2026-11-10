#!/usr/bin/env bash
# LWSM-1021 — runs INSIDE the build container; scripts/build-appimage.sh starts
# it. Freezes the app with PyInstaller and wraps the folder with appimagetool.
#
# Mounts: /src the project (read-only), /work requirements.txt and a download
# cache, /out where the AppImage goes. Environment: VERSION, APPIMAGE.
set -euo pipefail

APP_ID="io.github.milnet01.LocalWebServerManager"
APPDIR=/tmp/AppDir

echo "-- installing build tools and Qt's system libraries --"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
# Build tools: binutils for PyInstaller, file for appimagetool.
# The rest are libraries Qt links but the wheel does not carry. They must be
# present here so PyInstaller can load Qt and copy them into the bundle; a bare
# machine may lack them. Those every desktop has are removed again after the
# freeze (packaging/appimage-excludelist). libxkbcommon0 is left out on purpose: it must pair with the
# host's libxkbcommon-x11 and keyboard data, and a bundled half crashed
# finbreak's AppImage (its FIBR-0208).
apt-get install -y -qq --no-install-recommends \
    binutils file ca-certificates \
    libglib2.0-0 libgl1 libegl1 libdbus-1-3 libx11-6 \
    libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-image0 \
    libxcb-render-util0 libxcb-util1 libxcb-render0 libxcb-xkb1 libx11-xcb1 \
    libfreetype6 libfontconfig1 libharfbuzz0b \
    libgssapi-krb5-2 >/dev/null
# libgssapi-krb5-2: QtNetwork links it, and PyInstaller imports QtNetwork
# while freezing, so the build fails without it.

echo "-- installing the locked dependencies --"
export PIP_CACHE_DIR=/work/cache/pip
python3 -m venv /tmp/venv
# shellcheck disable=SC1091
. /tmp/venv/bin/activate
python -m pip install --quiet --no-deps --require-hashes -r /work/requirements.txt

echo "-- freezing --"
# A folder, not one file: the AppImage is already a single mounted image, and
# a one-file build would unpack itself into /tmp on every launch.
pyinstaller --onedir --noconfirm --name lwsm \
    --paths /src/src \
    --collect-submodules lwsm \
    --distpath /tmp/dist --workpath /tmp/build --specpath /tmp \
    /src/src/lwsm/__main__.py

echo "-- removing libraries the host provides --"
# PyInstaller copies every library Qt links, including ones each desktop
# already has. A bundled copy older than the host's breaks the host's use of
# it: Debian 12's fontconfig cannot read a newer system's font rules, and an
# old libstdc++ crashes a newer GL driver. The list is AppImage's own.
sed -e 's/#.*//' -e 's/[[:space:]]*$//' -e '/^$/d' /src/packaging/appimage-excludelist |
    while read -r lib; do
        find /tmp/dist/lwsm -name "$lib" -printf 'removed %f\n' -delete
    done

echo "-- fetching appimagetool and the AppImage runtime --"
# Both pinned to a numbered release and checked against the digest GitHub
# records for the asset. Without --runtime-file, appimagetool downloads the
# rolling `continuous` runtime, which would put unpinned code at the front of
# every AppImage. Checked on every run, because the cache outlives a release.
fetch() {
    local url="$1" sha="$2" dest="$3"
    if [ ! -f "$dest" ]; then
        python -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], sys.argv[2])' "$url" "$dest.part"
        mv "$dest.part" "$dest"
    fi
    if ! echo "$sha  $dest" | sha256sum -c - >/dev/null; then
        echo "_appimage-build: CHECKSUM MISMATCH for $dest — deleted; run again to re-download" >&2
        rm -f "$dest"
        exit 1
    fi
    chmod +x "$dest"
}
APPIMAGETOOL_VERSION=1.9.1
RUNTIME_VERSION=20251108
TOOL="/work/cache/appimagetool-$APPIMAGETOOL_VERSION-x86_64.AppImage"
RUNTIME="/work/cache/runtime-$RUNTIME_VERSION-x86_64"
fetch "https://github.com/AppImage/appimagetool/releases/download/$APPIMAGETOOL_VERSION/appimagetool-x86_64.AppImage" \
    ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0 "$TOOL"
fetch "https://github.com/AppImage/type2-runtime/releases/download/$RUNTIME_VERSION/runtime-x86_64" \
    2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d "$RUNTIME"

echo "-- assembling the AppDir --"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps"
cp -a /tmp/dist/lwsm "$APPDIR/usr/lib/lwsm"
cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/lwsm/lwsm" "$@"
EOF
chmod +x "$APPDIR/AppRun"
# The packaged entry, less TryExec: a menu entry made from the AppImage would
# be hidden on a machine with no `lwsm` on PATH.
sed -e '/^TryExec=/d' "/src/packaging/$APP_ID.desktop" > "$APPDIR/$APP_ID.desktop"
echo "X-AppImage-Version=$VERSION" >> "$APPDIR/$APP_ID.desktop"
cp "$APPDIR/$APP_ID.desktop" "$APPDIR/usr/share/applications/"
cp "/src/packaging/$APP_ID.svg" "$APPDIR/$APP_ID.svg"
cp "/src/packaging/$APP_ID.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
ln -s "$APP_ID.svg" "$APPDIR/.DirIcon"

echo "-- building the AppImage --"
# A container has no FUSE, so the tool extracts itself and runs. There is no
# AppStream metainfo yet, so its check is skipped.
ARCH=x86_64 "$TOOL" --appimage-extract-and-run --no-appstream \
    --runtime-file "$RUNTIME" "$APPDIR" "/out/$APPIMAGE"
