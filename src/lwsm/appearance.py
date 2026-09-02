"""What the desktop says it wants the app to look like.

Core, and like `placement.py` it imports no Qt at all. Everything here is a
subprocess call and a string parse, so it is worth testing without a display.

**Only the contrast preference lives here, and that is the whole reason the
module exists.** Qt reports the desktop's light/dark choice itself, live, via
`QStyleHints.colorScheme()` and its `colorSchemeChanged` signal — so asking
anyone else for that would be a second answer to a settled question. Qt has no
counterpart for contrast: measured against the PySide6 pinned here, `Qt` does
declare a `ContrastPreference` enum with a `HighContrast` member, and
`QStyleHints` exposes no accessor that returns one. The XDG settings portal
does, so this is the only route to it.

The portal is asked over `dbus-send`, which `placement.py` already depends on
and which is the reason no D-Bus binding is a dependency of this project.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable

from lwsm import applog

log = applog.get_logger(__name__)

# `placement.py`'s bound, restated rather than imported: that one paces three
# calls to KWin, this one paces a single read of a settings service, and tying
# them together would make a change to either a change to both.
DBUS_TIMEOUT_S = 3.0

PORTAL_NAMESPACE = "org.freedesktop.appearance"
PORTAL_CONTRAST_KEY = "contrast"

# `org.freedesktop.appearance/contrast`: 0 is no preference, 1 is higher
# contrast. Anything else is a value this build does not know, and is read as
# no preference rather than guessed at.
_CONTRAST_HIGH = 1

# The reply nests the value in two variants — `variant variant uint32 0` — so
# the number is taken by name rather than by position.
_UINT32 = re.compile(r"uint32\s+(\d+)")


def high_contrast(
    run: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> bool:
    """True only when the desktop actually asks for higher contrast.

    Every failure — no `dbus-send`, no portal answering, a timeout, a reply
    that does not parse — returns False, and the asymmetry is deliberate. A
    wrong True forces an assistive palette on someone who never asked for one
    and cannot see why. A wrong False leaves them exactly where they are
    today, with all eight palettes still in the picker one click away. So the
    unknown case is reported as the absence of a preference, which is also
    what the portal's own 0 means, rather than as a preference we invented.

    `run` and `which` are resolved in the body, not in the signature: a default
    bound to a module function is captured when this function is *defined*, so
    no monkeypatch of `subprocess` or `shutil` would ever reach it.
    """
    runner = subprocess.run if run is None else run
    look_up = shutil.which if which is None else which

    if look_up("dbus-send") is None:
        # Not a warning: a desktop without `dbus-send` is a supported one, and
        # the answer here is the same "no preference stated" it would give.
        log.debug("no dbus-send, so the contrast preference cannot be read")
        return False

    try:
        # An argument vector, never a shell string (`coding.md § O4`).
        result = runner(
            [
                "dbus-send",
                "--session",
                "--print-reply",
                "--dest=org.freedesktop.portal.Desktop",
                "/org/freedesktop/portal/desktop",
                "org.freedesktop.portal.Settings.Read",
                f"string:{PORTAL_NAMESPACE}",
                f"string:{PORTAL_CONTRAST_KEY}",
            ],
            capture_output=True,
            timeout=DBUS_TIMEOUT_S,
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        log.debug("could not read the contrast preference: %s", exc)
        return False

    if result.returncode != 0:
        # Expected wherever no portal is running, which is most non-Flatpak
        # desktops outside KDE and GNOME. Debug, not warning: this is a
        # question the app asks on the chance of an answer, not a failure.
        log.debug(
            "the settings portal declined the contrast read: %s",
            result.stderr.decode("utf-8", "replace").strip()
            or f"exit status {result.returncode}",
        )
        return False

    match = _UINT32.search(result.stdout.decode("utf-8", "replace"))
    if match is None:
        log.debug("the contrast reply carried no uint32 to read")
        return False
    return int(match.group(1)) == _CONTRAST_HIGH
