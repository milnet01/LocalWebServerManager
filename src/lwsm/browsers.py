"""The browsers this desktop already knows about, and opening a URL in one.

LWSM-1187. Core module with no Qt at all, not even `QtCore` — the same footing
as `placement.py` and `scanner.py` (`coding.md § O1`), so every rule below is
testable with no display.

**Nothing here runs a command the user typed, and that is the whole design.**
The candidates are the desktop's own registered `x-scheme-handler/http`
handlers: entries this session would already run for any clicked link. So a
per-project browser adds no new "execute a string named in a config file"
surface, which is the surface ADR-0003's trust model exists to gate. A
free-text command would have needed that gate; reading the handler list avoids
needing it at all.

Everything read here belongs to somebody else — entries installed by packages,
or dropped into the user's own `~/.local/share/applications`. So every read
goes through `configfile.read_bounded`, and **every entry is parsed inside its
own `try`**: one unreadable, oversized or hostile `.desktop` file must cost its
own entry and never the whole list. That containment rule is the one this
project learned four times over in `scanner.py` before stating it as a class
(`CLAUDE.md`, the `pathlib`/`EACCES` trap) — the fix is per-item containment,
not a fifth guard on a fifth call site.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lwsm.configfile import ConfigFileError, read_bounded

# The two MIME types that make an application a browser as far as the desktop
# is concerned. An entry claiming either is one the session would hand a link
# to already.
HTTP_HANDLERS = ("x-scheme-handler/http", "x-scheme-handler/https")

# Desktop Entry spec field codes. `%u`/`%U` take the URL and `%f`/`%F` a local
# path — a browser handed an http URL gets it either way, since the spec's own
# note is that a `%f` handler for a remote URL receives a local copy and no
# browser in the wild declares one for http. The rest are dropped: `%d %D %n %N
# %v %m` are deprecated outright, and `%i %c %k` expand from keys this module
# deliberately does not carry.
_URL_CODES = frozenset({"%u", "%U", "%f", "%F"})
_DROPPED_CODES = frozenset({"%d", "%D", "%n", "%N", "%v", "%m", "%i", "%c", "%k"})

# A URL is passed to another program as `argv`, so it must not be able to read
# as an option. `http://` and `https://` cannot begin with `-`; nothing else is
# accepted, and this is a refusal rather than an escape because there is no
# legitimate caller with a third scheme (`mainwindow.project_url` builds the
# only URL that reaches here).
_ALLOWED_SCHEMES = ("http://", "https://")


class BrowserError(Exception):
    """A chosen browser could not be launched."""


@dataclass(frozen=True)
class Browser:
    """One desktop entry that declares itself an http handler.

    `entry_id` is the desktop file's **base name** (`firefox.desktop`), and it
    is what `projects.json` stores. Not the absolute path: a path is
    machine-specific, and LWSM-1148 exports a profile from one machine and
    imports it on another, where the same browser sits under a different
    prefix. The base name is the desktop entry's own identity for exactly that
    reason.
    """

    entry_id: str
    name: str
    argv: tuple[str, ...]


def entry_dirs() -> tuple[Path, ...]:
    """`applications/` under XDG_DATA_HOME then XDG_DATA_DIRS, in precedence order.

    The user's own directory first, because the XDG base-directory spec makes
    it override the system ones — a locally-installed browser entry shadowing a
    packaged one of the same id is the case that matters.
    """
    home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    system = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    parts = [home, *system.split(":")]
    return tuple(Path(p) / "applications" for p in parts if p)


def parse_exec(value: str) -> tuple[str, ...]:
    """Tokenise a desktop entry's `Exec=` value per the Desktop Entry spec.

    Split on unquoted whitespace; a double-quoted string is one token, and
    inside one a backslash escapes the next character. Deliberately **not**
    `shlex.split`, whose POSIX-shell rules differ from the spec's on single
    quotes and backslashes — and the point of parsing at all rather than
    handing the string to a shell is that no shell ever sees it.
    """
    tokens: list[str] = []
    current: list[str] = []
    quoted = False
    escaped = False
    started = False

    for char in value:
        if escaped:
            current.append(char)
            escaped = False
        elif quoted and char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
            started = True
        elif quoted or not char.isspace():
            current.append(char)
            started = True
        elif started:
            tokens.append("".join(current))
            current = []
            started = False

    if started:
        tokens.append("".join(current))
    return tuple(tokens)


def expand(argv: tuple[str, ...], url: str) -> tuple[str, ...]:
    """Substitute the URL for the entry's field code, dropping the rest.

    A token that is exactly a URL code becomes the URL. A token that is exactly
    a dropped code disappears — `%i` in particular expands to *two* arguments
    or none, so leaving it in place would pass a literal `%i` to the browser.
    `%%` is the spec's escape for a literal percent.

    Where the entry declares no URL code at all the URL is appended, which is
    what a desktop launcher does with a handler whose author left it out.
    """
    out: list[str] = []
    substituted = False
    for token in argv:
        if token in _URL_CODES:
            out.append(url)
            substituted = True
        elif token in _DROPPED_CODES:
            continue
        else:
            out.append(token.replace("%%", "%"))
    if not substituted:
        out.append(url)
    return tuple(out)


def _entry_fields(text: str) -> dict[str, str]:
    """The `[Desktop Entry]` group's keys, and no other group's.

    A `.desktop` file also carries `[Desktop Action ...]` groups, each with its
    own `Exec=`. Reading those would launch the wrong thing — "Open a New
    Private Window" instead of the browser — so the scan stops at the next
    group header.
    """
    fields: dict[str, str] = {}
    in_entry = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_entry = stripped == "[Desktop Entry]"
            continue
        if not in_entry or "=" not in stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        # First wins: a duplicated key is malformed, and taking the first is
        # what the spec's own parsers do.
        fields.setdefault(key.strip(), value.strip())
    return fields


def _browser_from(path: Path) -> Browser | None:
    """One desktop entry, or `None` if it is not a browser we can launch."""
    fields = _entry_fields(read_bounded(path).decode("utf-8"))

    if fields.get("Type", "Application") != "Application":
        return None
    if fields.get("NoDisplay", "").lower() == "true":
        return None
    if fields.get("Hidden", "").lower() == "true":
        return None

    mime = fields.get("MimeType", "")
    if not any(handler in mime for handler in HTTP_HANDLERS):
        return None

    # `TryExec` is the spec's own "is this actually installed" key. Honouring it
    # is what keeps a stale entry for an uninstalled browser out of the list,
    # which would otherwise be offered and then fail at the click.
    try_exec = fields.get("TryExec", "")
    if try_exec and shutil.which(try_exec) is None and not Path(try_exec).exists():
        return None

    argv = parse_exec(fields.get("Exec", ""))
    if not argv:
        return None

    name = fields.get("Name", "") or path.stem
    return Browser(entry_id=path.name, name=name, argv=argv)


def installed(dirs: tuple[Path, ...] | None = None) -> tuple[Browser, ...]:
    """Every browser the desktop registers, first definition of an id winning.

    `dirs` defaults to `None` and is resolved in the body rather than in the
    signature: a default bound to `entry_dirs()` would be evaluated once at
    import and could never be monkeypatched, which is the trap LWSM-1033 paid a
    cycle for and nearly paid a second.

    Sorted by name so the dropdown does not reorder itself between runs on
    directory-iteration order.
    """
    found: dict[str, Browser] = {}
    for directory in entry_dirs() if dirs is None else dirs:
        try:
            entries = sorted(directory.glob("*.desktop"))
        except OSError:
            # An unreadable applications directory is one directory's worth of
            # browsers lost, never the whole list.
            continue
        for path in entries:
            if path.name in found:
                continue
            try:
                browser = _browser_from(path)
            except (ConfigFileError, OSError, UnicodeDecodeError, ValueError):
                # Per entry, deliberately. See the module docstring: one hostile
                # file costs its own entry and nothing else.
                continue
            if browser is not None:
                found[path.name] = browser
    return tuple(sorted(found.values(), key=lambda b: (b.name.lower(), b.entry_id)))


def by_id(browsers: tuple[Browser, ...], entry_id: str | None) -> Browser | None:
    """The browser with this id, or `None` — for no choice and for a stale one.

    A stored id whose browser has since been uninstalled returns `None` and is
    therefore treated exactly as "no choice": the caller falls back to the
    desktop default rather than failing. The choice stays in the file, so
    reinstalling the browser restores it.
    """
    if entry_id is None:
        return None
    return next((b for b in browsers if b.entry_id == entry_id), None)


def open_url(browser: Browser, url: str) -> None:
    """Launch `browser` on `url`, detached. Raises `BrowserError` on failure.

    `start_new_session=True` puts the browser in its own process group. That is
    not decoration here: `supervisor.stop()` signals process *groups*, and a
    browser sharing ours would be a live candidate for a signal aimed at a
    server. It also outlives this app, which is what a user expects of a
    browser they opened from it.

    No `shell=True`, and no string command anywhere — `argv` throughout.
    """
    if not url.startswith(_ALLOWED_SCHEMES):
        raise BrowserError(f"refusing to open {url!r}: not an http(s) URL")

    argv = expand(browser.argv, url)
    try:
        subprocess.Popen(  # noqa: S603
            argv,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise BrowserError(f"could not launch {browser.name}: {exc}") from exc
