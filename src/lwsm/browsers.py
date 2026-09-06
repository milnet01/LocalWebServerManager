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

**Registered means resolved, not merely claimed** (LWSM-1248). An entry's own
`MimeType` starts the association and the desktop's `mimeapps.list` settles it,
so `[Removed Associations]` takes a browser back out of this list and
`[Added Associations]` puts one in. Reading the `MimeType` alone offered a
browser the user had explicitly removed, which is why that claim is load-bearing
rather than descriptive.

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

from lwsm import applog
from lwsm.configfile import ConfigFileError, display_text, quoted, read_bounded

log = applog.get_logger(__name__)

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


def _under_home(*parts: str) -> str | None:
    """`~/<parts>`, or `None` when this process has no home directory.

    `Path.home()` RAISES rather than returning something falsy when `HOME` is
    unset, and both callers below reach it only as a fallback for an unset XDG
    variable — so the failure arrives in the rare configuration and never in
    the one anybody develops against.

    It must not propagate. These lookups run inside `MainWindow.__init__`, and
    an exception there leaves a half-built window whose every later event
    raises on an attribute that was never assigned: the visible failure is then
    a Qt `changeEvent` traceback naming neither the home directory nor this
    module. Answering `None` drops one search root, which is what a machine
    with no home directory actually has.
    """
    try:
        return str(Path.home().joinpath(*parts))
    except RuntimeError:
        log.info("no home directory; skipping its desktop-entry search root")
        return None


def entry_dirs() -> tuple[Path, ...]:
    """`applications/` under XDG_DATA_HOME then XDG_DATA_DIRS, in precedence order.

    The user's own directory first, because the XDG base-directory spec makes
    it override the system ones — a locally-installed browser entry shadowing a
    packaged one of the same id is the case that matters.
    """
    home = os.environ.get("XDG_DATA_HOME") or _under_home(".local", "share")
    system = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    parts = [home, *system.split(":")]
    return tuple(Path(p) / "applications" for p in parts if p)


def mimeapps_paths() -> tuple[Path, ...]:
    """The `mimeapps.list` files, highest precedence first (LWSM-1248).

    The MIME Applications Associations spec's search order: config dirs before
    data dirs, and within each a `$desktop-mimeapps.list` before the plain one.
    `XDG_CURRENT_DESKTOP` is a colon-separated list, most specific first.

    `[Default Applications]` is only honoured in the config dirs; this module
    reads associations alone, so that distinction costs nothing here.
    """
    config_home = os.environ.get("XDG_CONFIG_HOME") or _under_home(".config")
    config_dirs = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    desktops = [
        part.strip().lower()
        for part in (os.environ.get("XDG_CURRENT_DESKTOP") or "").split(":")
        if part.strip()
    ]
    names = [*(f"{d}-mimeapps.list" for d in desktops), "mimeapps.list"]

    roots = [Path(p) for p in [config_home, *config_dirs.split(":")] if p]
    # The data-dir copies are deprecated by the spec but still shipped — this
    # machine's own KDE association file is one of them.
    roots += [d for d in entry_dirs()]
    return tuple(root / name for root in roots for name in names)


def _groups(text: str) -> dict[str, dict[str, str]]:
    """Every group's keys, for a file whose groups all matter.

    `_entry_fields` deliberately reads one group; a `mimeapps.list` is several
    and the caller needs each by name.
    """
    groups: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = groups.setdefault(stripped[1:-1], {})
            continue
        if current is None or "=" not in stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        current.setdefault(key.strip(), value.strip())
    return groups


def _associations(paths: tuple[Path, ...]) -> tuple[dict[str, bool], list[str]]:
    """Which entry ids the desktop adds to, or removes from, the http handlers.

    Returns `{entry_id: added}` and the reasons for any file that could not be
    read. **First mention of an id wins**, across files and within one: the
    spec resolves per entry id rather than per file, so a user config that adds
    an entry beats a system list that removes it. `Added` is read before
    `Removed` in the same file, which the spec leaves undefined.

    Every file here belongs to somebody else, so each is read inside its own
    `try` for the module docstring's reason.
    """
    state: dict[str, bool] = {}
    reasons: list[str] = []
    for path in paths:
        try:
            groups = _groups(read_bounded(path).decode("utf-8"))
        except FileNotFoundError:
            # Absent is the normal case, not a failure: the spec lists many
            # candidate paths and a desktop writes few of them.
            continue
        except (ConfigFileError, OSError, UnicodeDecodeError, ValueError) as exc:
            reasons.append(f"{quoted(path.name)}: {quoted(exc)}")
            log.info("ignoring %s: %s", path, exc)
            continue
        for group, added in (
            ("Added Associations", True),
            ("Removed Associations", False),
        ):
            keys = groups.get(group, {})
            for handler in HTTP_HANDLERS:
                for entry_id in keys.get(handler, "").split(";"):
                    if entry_id.strip():
                        state.setdefault(entry_id.strip(), added)
    return state, reasons


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


def _browser_from(path: Path, *, mime_required: bool = True) -> Browser | None:
    """One desktop entry, or `None` if it is not a browser we can launch.

    `mime_required` is `False` for an entry the desktop's own `mimeapps.list`
    adds to the http handlers (LWSM-1248): declaring no `MimeType` is exactly
    why such an entry cannot be found by the `MimeType` test. Every other
    refusal below still applies to it — an added entry that is hidden, or whose
    binary is gone, is no more launchable than any other.
    """
    fields = _entry_fields(read_bounded(path).decode("utf-8"))

    if fields.get("Type", "Application") != "Application":
        return None
    if fields.get("NoDisplay", "").lower() == "true":
        return None
    if fields.get("Hidden", "").lower() == "true":
        return None

    mime = fields.get("MimeType", "")
    if mime_required and not any(handler in mime for handler in HTTP_HANDLERS):
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

    # Sanitised and clipped, because a `.desktop` file belongs to whoever put
    # it on the machine (LWSM-1249). The name reaches a combo item, a tooltip
    # and an accessible name, and a `Name` may carry a newline — the
    # forged-log-record shape LWSM-1078 closed for scan roots. It also lands
    # in a `horizontalAdvance()` call per row on every font change: measured
    # 2026-09-06, a 1 MiB name costs 106 ms there against 0.5 ms at the
    # display limit.
    #
    # The DISPLAY limit rather than the bullet's 4096, which is
    # `MAX_SOURCE_LINE_CHARS` — the per-line bound for scanning somebody's
    # source. This is a name shown in the UI, which is the case this project
    # already bounds at `MAX_DISPLAY_NAME_CHARS`, with this same sanitiser,
    # for a project's name.
    #
    # The `path.stem` fallback is sanitised too: on Linux a FILENAME may hold
    # a newline, and that branch needs no valid key to reach.
    name = display_text(fields.get("Name", "") or path.stem)
    return Browser(entry_id=path.name, name=name, argv=argv)


@dataclass(frozen=True)
class LoadResult:
    """What the scan found, and what it had to skip to say so (LWSM-1250).

    `registry.LoadResult`'s shape, for `settings.LoadResult`'s reason: the
    browsers are always usable, and `reasons` says what was ignored to get
    them. The scan never raises — one hostile entry costs its own entry.

    **`refused` carries the entry IDS and not just a count**, and that is the
    whole point of the item. `by_id` returns `None` for an id that was never
    there and for one whose file could not be parsed, so without this the
    window told a user their chosen browser "is not installed" about a browser
    that is installed, pointing them at reinstalling it.
    """

    browsers: tuple[Browser, ...]
    reasons: tuple[str, ...] = ()
    refused: frozenset[str] = frozenset()


def installed(
    dirs: tuple[Path, ...] | None = None,
    *,
    mimeapps: tuple[Path, ...] | None = None,
) -> LoadResult:
    """Every browser the desktop would hand a link to, first definition winning.

    **The desktop's answer, not the entries' own claim** (LWSM-1248). An entry's
    `MimeType` is where the association starts, and `mimeapps.list` is where the
    user settles it: `[Removed Associations]` takes a browser back out, and
    `[Added Associations]` puts one in that never declared the handler. Reading
    the `MimeType` alone was both too wide and too narrow, and the wide half is
    the one that matters — it offered a browser the user had explicitly removed.

    `dirs` and `mimeapps` default to `None` and are resolved in the body rather
    than in the signature: a default bound to a function would be evaluated once
    at import and could never be monkeypatched, which is the trap LWSM-1033 paid
    a cycle for and nearly paid a second.

    Sorted by name so the dropdown does not reorder itself between runs on
    directory-iteration order.
    """
    associations, reasons = _associations(
        mimeapps_paths() if mimeapps is None else mimeapps
    )
    found: dict[str, Browser] = {}
    refused: set[str] = set()
    for directory in entry_dirs() if dirs is None else dirs:
        try:
            entries = sorted(directory.glob("*.desktop"))
        except OSError as exc:
            # An unreadable applications directory is one directory's worth of
            # browsers lost, never the whole list — but it is still a failure
            # with a home (LWSM-1250). No id is recorded: nothing here names a
            # browser, so there is nothing a caller could match against.
            reasons.append(f"{quoted(str(directory))}: {quoted(exc)}")
            log.info("ignoring applications directory %s: %s", directory, exc)
            continue
        for path in entries:
            if path.name in found:
                continue
            association = associations.get(path.name)
            if association is False:
                # Explicitly removed by the desktop. Skipped before the read,
                # because a removed entry is not offered from any directory and
                # its file is one this module then has no reason to open.
                continue
            try:
                browser = _browser_from(path, mime_required=association is not True)
            except (ConfigFileError, OSError, UnicodeDecodeError, ValueError) as exc:
                # Per entry, deliberately. See the module docstring: one hostile
                # file costs its own entry and nothing else.
                #
                # Reported rather than swallowed (LWSM-1250). `design.md` —
                # "Every failure has a visible home... Nothing is swallowed" —
                # and the id is kept so a caller can tell a refused entry from
                # an absent one.
                refused.add(path.name)
                reasons.append(f"{quoted(path.name)}: {quoted(exc)}")
                log.info("ignoring desktop entry %s: %s", path.name, exc)
                continue
            if browser is not None:
                found[path.name] = browser
    return LoadResult(
        browsers=tuple(
            sorted(found.values(), key=lambda b: (b.name.lower(), b.entry_id))
        ),
        reasons=tuple(reasons),
        refused=frozenset(refused),
    )


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
