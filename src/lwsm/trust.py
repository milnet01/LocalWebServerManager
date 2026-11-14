"""The trust gate: which launchers run, and what a confirmation binds to.

Core module — no Qt at all (`docs/standards/coding-overrides.md § O1`). A
discovered launcher is untrusted until the user confirms it (LWSM-1046,
ADR-0003 § Trust). This module decides whether a launcher is acceptable at all
(`validate_launcher`), fingerprints what a confirmation is bound to
(`launcher_fingerprint`, with the `npm run` material), and holds the refusals
`start()` raises. `stores.TrustStore` keeps the confirmations; `supervisor.py`
spawns. `SupervisorError` is defined here, as the root of the refusals both
modules raise, so this module need not import the one that imports it.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

# A launcher is somebody else's file, so reading it to fingerprint it is a
# bounded read like every other. Larger than `scanner.py`'s cap because this is
# a whole-file hash rather than a line scan, and a 1 MiB shell script is already
# absurd.
MAX_LAUNCHER_BYTES = 1 << 20


class SupervisorError(Exception):
    """Anything the trust gate or the supervisor refuses or fails to do."""


class LauncherRefused(SupervisorError):
    """The launcher is one ADR-0003 § Trust refuses outright.

    Distinct from `LauncherUntrusted`: this one cannot be confirmed away. A
    world-writable launcher is not a thing the user can vouch for, because
    whoever else can write it changes what they vouched for afterwards.
    """


class LauncherUntrusted(SupervisorError):
    """The launcher has not been confirmed, or has changed since it was.

    Carries the material the confirmation must show — ADR-0003: "not security
    theatre only if it shows what will actually run: the resolved path and
    argv, never a friendly summary".
    """

    def __init__(
        self,
        resolved: Path | None,
        argv: tuple[str, ...],
        fingerprint: str,
        npm_shown: tuple[tuple[str, str], ...] = (),
    ):
        super().__init__(
            f"{resolved or argv[0]} has not been confirmed for this project"
        )
        self.resolved = resolved
        self.argv = argv
        self.fingerprint = fingerprint
        # For `npm run`, what `/bin/sh` will run and the `.npmrc` that shapes
        # it, as (label, text) pairs: `npm` itself shows nothing (LWSM-1365).
        self.npm_shown = npm_shown


# --------------------------------------------------------------------------
# The trust gate (LWSM-1046)
# --------------------------------------------------------------------------


def is_npm_run(argv: tuple[str, ...]) -> bool:
    """`npm run <script>` — the one supported shape that names no file.

    Stated once because two callers need it and they must agree: `npm_material`
    hashes the manifest string this shape executes, and `start()` refuses any
    other shape that names no launcher (LWSM-1228). A second copy that drifted
    would either hash nothing or refuse a launcher that works.
    """
    return len(argv) == 3 and argv[0] == "npm" and argv[1] == "run"


def launcher_path(project: Path, argv: tuple[str, ...]) -> Path | None:
    """The file whose contents `argv` executes, if any — refused by the caller.

    Classification only. Whether that file is *acceptable* — inside the
    project, a regular file, not group-writable — is `validate_launcher`'s,
    and `start()` calls it on whatever this returns.

    Two of the four shapes `scanner.py` emits have one. `["./start.sh"]` names
    it directly. `["python3", "serve.py"]` and `["node", "serve.mjs"]` name it
    as the sole argument to a PATH-resolved interpreter — `execve` runs
    `/usr/bin/python3`, but the untrusted content is the script, and that is
    what a confirmation has to be bound to and what `validate_launcher`'s
    refusals have to cover.

    `["npm", "run", "dev"]` has none: what it executes is the `scripts.dev`
    *string* inside `package.json`, which is not a file. `launcher_fingerprint`
    covers that case separately.

    **An `argv[0]` containing no `/` is resolved against `PATH` by `execvp` and
    never against the working directory — POSIX decides this, not path
    arithmetic.** Building `<project>/npm` and letting the caller's `os.stat`
    fail on it refused three of the four launcher kinds outright, with a
    message blaming the user's project for a supervisor bug (LWSM-1132).
    """
    if not argv:
        return None
    if "/" in argv[0]:
        return _as_written(project, argv[0])
    # npm's arguments are subcommands, never files — `npm_material` below is
    # what covers its content. Named explicitly because a *two*-element
    # `npm run` otherwise matches the interpreter shape below on length alone,
    # and a project holding a file called `run` would then have the trust gate
    # vouching for a file that has nothing to do with what executes.
    if argv[0] == "npm":
        return None
    # The interpreter form: one PATH-resolved command, one file it opens.
    if len(argv) == 2:
        return _as_written(project, argv[1])
    return None


def _as_written(project: Path, name: str) -> Path | None:
    """`name` joined to the project as written, or `None` when it names nothing
    or resolves to the project root.

    The path is returned UNRESOLVED, because `validate_launcher` has to walk the
    directories `execve` looks each written component up in, and a symlink on
    the way is invisible once resolved (LWSM-1352).

    **Escaping is deliberately NOT filtered here** — that is the whole of
    LWSM-1162. A symlink leaving the project is a launcher to REFUSE, not a
    launcher we do not have, and returning `None` for it made `launcher_path`
    give the same answer it gives `npm run dev`. So `validate_launcher` was
    never reached from `start()`, its "outside the project directory" refusal
    was unreachable, and the fingerprint fell through to the `\0nofile\0`
    marker — hashing argv alone, so rewriting the target could not re-arm the
    gate. Containment is `validate_launcher`'s decision, on the resolved target
    that `execve` will actually run; this function only says which file `argv`
    names.
    """
    try:
        project_resolved = Path(project).resolve()
        written = project_resolved / Path(name)
        resolved = written.resolve()
    except OSError:
        return None
    if resolved == project_resolved:
        return None
    return written


def validate_launcher(project: Path, launcher: Path) -> Path:
    """Refuse the launchers ADR-0003 § Trust refuses outright; return the target.

    Two refusals, and they are about the resolved *target* because that is what
    `execve` runs: a symlink leaving the project, and a file any other local
    account can rewrite. A symlink that stays inside the project is fine — the
    ordinary `start.sh -> scripts/start.sh` arrangement — since refusing it
    would fire on the legitimate case, and a rule that does that gets disabled.

    A residual race is accepted here, deliberately (LWSM-1320, user decision
    2026-09-28). The launcher's name is resolved three times: the `stat` below,
    the open in `bounded_regular_bytes` that fingerprints it, and the kernel's at
    `Popen`. A file swapped between them is not the one that was checked
    (CWE-367). Closing it means executing the checked descriptor (`fexecve` or
    `/proc/self/fd/N`), which changes `$0` and `__file__` for every launcher
    and breaks `cd "$(dirname "$0")"` and sibling imports — the ordinary shape
    of a launcher. What the checks below leave is narrow: to win the window an
    account must be able to replace the file. They refuse it unless only we or
    root can, on the file and on every directory up to the project root
    (LWSM-1226, LWSM-1333), and either of us already controls the account. A
    swap made outside the window changes the bytes, and the fingerprint
    re-arms the trust gate.
    """
    project_resolved = Path(project).resolve()
    try:
        resolved = Path(launcher).resolve()
    except OSError as exc:
        raise LauncherRefused(f"cannot resolve {launcher}: {exc}") from exc

    if not resolved.is_relative_to(project_resolved):
        raise LauncherRefused(
            f"{launcher} resolves to {resolved}, outside the project directory"
        )
    try:
        info = os.stat(resolved)
    except OSError as exc:
        raise LauncherRefused(f"cannot read {resolved}: {exc}") from exc

    if not stat.S_ISREG(info.st_mode):
        raise LauncherRefused(f"{resolved} is not a regular file")
    # Size, because the fingerprint is a bounded read. Hashing the first
    # `MAX_LAUNCHER_BYTES` of a larger file leaves everything past the cap out
    # of the digest, so a change there never re-arms the gate ADR-0003 re-arms
    # on a content change. Refusing here rather than hashing a prefix is
    # `scanner.py`'s discipline, and `start()` reaches this before it
    # fingerprints anything (LWSM-1227).
    if info.st_size > MAX_LAUNCHER_BYTES:
        raise LauncherRefused(
            f"{resolved} is larger than {MAX_LAUNCHER_BYTES} bytes, so it "
            "cannot be fingerprinted whole and a change past the cap would "
            "not re-arm the trust gate"
        )
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise LauncherRefused(
            f"{resolved} is group- or other-writable, so confirming it would "
            "vouch for whatever it is rewritten to say"
        )
    # Ownership, which nothing checked. A file we do not own can be rewritten
    # by whoever does, whatever its mode says. Root is allowed: a root-owned
    # launcher in a directory we control is the ordinary shape of a
    # system-installed one (LWSM-1226).
    if info.st_uid not in (os.getuid(), 0):
        raise LauncherRefused(
            f"{resolved} is owned by uid {info.st_uid}, who can rewrite it "
            "after it is confirmed"
        )
    # And every DIRECTORY from the launcher's up to the project root, because
    # replacing a file needs write permission on its directory rather than on
    # the file, and replacing a directory needs it on that directory's parent.
    # The refusals above read the launcher's own inode, and unlink-and-create
    # defeats them outright — `0755` on the file is no protection in a
    # directory someone else can write (LWSM-1226), or that someone else owns,
    # whatever its mode says (LWSM-1333).
    #
    # The sticky bit exempts the mode check and it is the common case: `/tmp`
    # is `1777`, and with it set only the owner may unlink. It exempts nothing
    # from the ownership check, since the directory's owner is that owner.
    #
    # The walk stops at the project root. Directories above it are where the
    # user chose to keep the project, and not the project's to vouch for.
    checked: set[Path] = set()
    for directory in (resolved.parent, *resolved.parent.parents):
        _refuse_replaceable_directory(directory)
        checked.add(directory)
        if directory == project_resolved:
            break
    # And every directory resolution looks a WRITTEN component up in. A
    # symlink on the path as argv names it — `./bin/start.sh` with `bin` a
    # link — lives in a directory the walk above never visits, since that walk
    # starts from the resolved target. Swapping the link needs write on the
    # directory holding it, so that directory meets the same refusals
    # (LWSM-1352). Ancestors of the project root are skipped for the reason
    # above. A path written under the project as passed is rebased onto the
    # resolved root, so a symlink in the project's OWN location is not walked.
    written = Path(launcher)
    if written.is_relative_to(project):
        written = project_resolved / written.relative_to(project)
    for directory in _lookup_directories(project_resolved, written):
        if directory in checked:
            continue
        if directory != project_resolved and project_resolved.is_relative_to(directory):
            continue
        _refuse_replaceable_directory(directory)
        checked.add(directory)
    return resolved


# Linux's limit on symlinks followed in one resolution (`SYMLOOP_MAX`).
_MAX_SYMLINK_HOPS = 40


def _lookup_directories(project: Path, launcher: Path) -> list[Path]:
    """Every directory in which resolving `launcher` looks a name up.

    Resolved one component at a time, as the kernel does, so a symlink met on
    the way contributes the directories ITS target is looked up in too. A
    relative `launcher` and one under `project` start from `project`; any
    other absolute one from `/`.
    """
    try:
        parts = list(launcher.relative_to(project).parts)
        current = project
    except ValueError:
        parts = list(launcher.parts)
        current = Path("/")
    directories: list[Path] = []
    hops = 0
    while parts:
        part = parts.pop(0)
        if part == "/":
            current = Path("/")
            continue
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            continue
        if current not in directories:
            directories.append(current)
        candidate = current / part
        if candidate.is_symlink():
            hops += 1
            if hops > _MAX_SYMLINK_HOPS:
                raise LauncherRefused(f"{launcher}: too many levels of symbolic links")
            try:
                target = os.readlink(candidate)
            except OSError as exc:
                raise LauncherRefused(f"cannot read {candidate}: {exc}") from exc
            parts = list(Path(target).parts) + parts
        else:
            current = candidate
    return directories


def _refuse_replaceable_directory(directory: Path) -> None:
    """Refuse a directory another account can use to replace what is in it."""
    try:
        info = os.stat(directory)
    except OSError as exc:
        raise LauncherRefused(f"cannot read {directory}: {exc}") from exc
    if info.st_uid not in (os.getuid(), 0):
        raise LauncherRefused(
            f"{directory} is owned by uid {info.st_uid}, who can replace "
            "the launcher after it is confirmed"
        )
    writable = info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    if writable and not info.st_mode & stat.S_ISVTX:
        raise LauncherRefused(
            f"{directory} is group- or other-writable without the sticky "
            "bit, so the launcher can be replaced after it is confirmed"
        )


def launcher_fingerprint(project: Path, argv: tuple[str, ...]) -> str:
    """What a confirmation is bound to: the exact argv, plus the launcher's bytes.

    Both halves are load-bearing. Content alone would let a confirmed
    `npm run dev` authorise `npm run deploy`, which reads the same file. Argv
    alone would let `./start.sh` be rewritten after confirmation, which is the
    re-arm ADR-0003 asks for and ADR-0005's merge already detects as *Changed*.
    """
    digest = hashlib.sha256()
    for argument in argv:
        digest.update(argument.encode("utf-8", "surrogateescape"))
        digest.update(b"\0")

    # An explicit marker per material kind rather than just skipping: without
    # one, a launcher that was deleted between two calls fingerprints
    # identically to `npm run dev`, which has no file at all — two different
    # situations reading as one. A third kind needs a third marker for the same
    # reason, so a script's bytes cannot collide with a manifest string.
    # Resolved here because `launcher_path` returns the path as written and
    # `bounded_regular_bytes` opens with `O_NOFOLLOW`, which would read a launcher
    # that is itself a symlink as missing (LWSM-1352).
    candidate = launcher_path(project, argv)
    try:
        target = candidate.resolve() if candidate is not None else None
    except OSError:
        target = None
    content = bounded_regular_bytes(target) if target is not None else None
    if content is not None:
        digest.update(b"\0content\0")
        digest.update(content)
        return digest.hexdigest()

    material = npm_material(project, argv)
    if material is not None:
        digest.update(b"\0npm-script\0")
        digest.update(material)
        return digest.hexdigest()

    digest.update(b"\0nofile\0")
    return digest.hexdigest()


def npm_material(project: Path, argv: tuple[str, ...]) -> bytes | None:
    """Everything an `npm run <name>` argv runs that lives in the project.

    That is three `scripts` strings, not one — npm runs `pre<name>` and
    `post<name>` around `<name>` — plus the project's `.npmrc`, whose
    `script-shell` and `node-options` change what any of them executes. A
    `git pull` adding any of these ran new code under the old confirmation
    (LWSM-1363). Each part is framed by a marker and its length, and an absent one
    contributes a marker too, so adding one changes the hash.

    `npm` is on the PATH and runs no file of ours, so `launcher_path` returns
    `None` for it — but the string it executes is untrusted content living in
    the project, and ADR-0003 § Trust re-arms the gate *"whenever the launcher
    command or its content hash changes"*. A compromised transitive
    dependency's `postinstall` can rewrite `scripts.dev`, which changes what
    runs; without this the confirmation carried straight over to whatever it
    was rewritten to say (LWSM-1140).

    Only the chosen script and its two hooks, never the whole manifest:
    re-arming on every dependency bump would fire the confirmation dialog during
    ordinary development, and `validate_launcher` already records what happens
    to a rule that does that.

    Both files are resolved before reading, for the reason `launcher_fingerprint`
    resolves a launcher: `bounded_regular_bytes` opens with `O_NOFOLLOW`, so a
    symlinked `package.json` read as missing and hashed as a constant
    (LWSM-1364). Containment of the resolved target is `start()`'s check.

    Strings are encoded with `surrogatepass`: a JSON `"\\ud800"` decodes to a
    lone surrogate, which `surrogateescape` raises on (LWSM-1367).

    Every failure here returns `None`, and `start()` refuses an `npm run` shape
    that has none, so an unreadable script is never a state the user can
    confirm (LWSM-1364).
    """
    parts = _npm_parts(project, argv)
    if parts is None:
        return None
    scripts, config = parts

    # Length-prefixed, because a JSON string may hold `\0` and the marker text:
    # without the length, a script could be written to read as two.
    def framed(marker: bytes, content: bytes) -> bytes:
        return b"\0" + marker + b"\0" + str(len(content)).encode() + b":" + content

    material = b""
    for _, value in scripts:
        if value is None:
            material += framed(b"absent", b"")
        else:
            material += framed(b"script", value.encode("utf-8", "surrogatepass"))
    if config is None:
        return material + framed(b"no-npmrc", b"")
    return material + framed(b"npmrc", config)


def npm_shown(project: Path, argv: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    """What the trust dialog shows for `npm run <name>`: each script npm will
    run, then each line of the project's `.npmrc`, as (label, text) pairs.

    Read from the same parse `npm_material` hashes, so the dialog cannot show
    one thing while the confirmation binds to another (LWSM-1365). Empty for
    any other shape, or where the material could not be read — `start()` has
    already refused that case.
    """
    parts = _npm_parts(project, argv)
    if parts is None:
        return ()
    scripts, config = parts
    shown = [(key, value) for key, value in scripts if value is not None]
    if config is not None:
        text = config.decode("utf-8", "replace")
        shown += [(".npmrc", line) for line in text.splitlines() if line.strip()]
    return tuple(shown)


def _npm_parts(
    project: Path, argv: tuple[str, ...]
) -> tuple[tuple[tuple[str, str | None], ...], bytes | None] | None:
    """The three scripts in run order, each `None` where absent, and the
    `.npmrc` bytes, `None` where there is none. `None` overall when any of it
    cannot be read, or the named script itself is missing.
    """
    if not is_npm_run(argv):
        return None
    raw = _resolved_bytes(project / "package.json")
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict) or not isinstance(scripts.get(argv[2]), str):
        return None
    found: list[tuple[str, str | None]] = []
    for key in (f"pre{argv[2]}", argv[2], f"post{argv[2]}"):
        value = scripts.get(key)
        if value is not None and not isinstance(value, str):
            return None
        found.append((key, value))
    npmrc = project / ".npmrc"
    if not os.path.lexists(npmrc):
        return tuple(found), None
    config = _resolved_bytes(npmrc)
    if config is None:
        return None
    return tuple(found), config


def _resolved_bytes(path: Path) -> bytes | None:
    """`bounded_regular_bytes` of `path` with any symlink resolved first."""
    try:
        return bounded_regular_bytes(path.resolve())
    except OSError:
        return None


def bounded_regular_bytes(path: Path) -> bytes | None:
    """The content of one regular file, or `None` when it is unreadable, not a
    regular file or over the cap. Reads launchers, `package.json` and `.npmrc`.

    `O_NOFOLLOW` and `O_NONBLOCK` because a symlink here would be read straight
    through, and a FIFO planted at `start.sh` would block the fingerprint
    forever.

    **On the LAST path component only.** `scanner.py::_open_source` opens
    every component with `O_PATH|O_DIRECTORY|O_NOFOLLOW` (LWSM-1332); this does
    not, so a directory on the way could be swapped by whoever can write its
    parent. What covers that on the start path is `validate_launcher`, which
    refuses the launch unless only we or root can replace the launcher and
    every directory up to the project root — so only the user could make the
    swap (security pass, 2026-10-01; LWSM-1368).
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        # Read to EOF or one past the cap. A single `os.read` may return short,
        # which would hash a prefix as though it were the file
        # (known-issue-056, LWSM-1321).
        data = b""
        while len(data) <= MAX_LAUNCHER_BYTES:
            chunk = os.read(fd, MAX_LAUNCHER_BYTES + 1 - len(data))
            if not chunk:
                break
            data += chunk
    except OSError:
        return None
    finally:
        os.close(fd)
    # One byte past the cap, so "at the cap" and "over it" are distinguishable.
    # Over it is a refusal, never a prefix: a truncated read hashed as though it
    # were the whole file is the defect `validate_launcher` also refuses
    # (LWSM-1227). An oversize file therefore reaches `launcher_fingerprint`'s
    # `nofile` marker, which it shares with a launcher that does not exist — no
    # loss, because nothing can start one, and a marker of its own would still
    # collide oversize with oversize.
    return None if len(data) > MAX_LAUNCHER_BYTES else data
