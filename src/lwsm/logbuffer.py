"""Following a project's output into a bounded ring, for the log panel.

Core module — `QtCore` only, never `QtWidgets` (`docs/standards/coding-overrides.md
§ O1`), so all of it is tested without a display. The panel that shows it is
`logpanel.py`.

Contract: `docs/design.md § Observability` (the ring of the last 2000 lines,
kept after the server exits) and ADR-0003's verb table, whose logs row gives
the two sources:

- a process-managed project's own log file, which `Supervisor` writes and
  names (`Supervisor.log_path_for`); and
- a service-managed project's journal, `journalctl --user` for its unit.

Each source is followed on a plain thread of its own, which hands text to a
callback. `LogFeed` turns those callbacks into a queued Qt signal, so nothing
on the follower's thread touches a widget (`§ O2`). LWSM-1015.
"""

from __future__ import annotations

import codecs
import errno
import os
import re
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal

from lwsm.applog import _open_private_regular, get_logger
from lwsm.scanner import MAX_SOURCE_LINE_CHARS, valid_unit_name

log = get_logger(__name__)

# design.md § Observability: "the last N lines (default 2000)".
MAX_LINES = 2000

# design.md § Detection rules: "the LogPanel elides at" the canonical per-line
# limit, so one number governs every untrusted string the app shows.
MAX_LINE_CHARS = MAX_SOURCE_LINE_CHARS

# How often a file is checked for growth. A quarter-second reads as live and
# costs one `fstat` per tick on one file, since only one panel is open.
POLL_SECONDS = 0.25

# How much of an existing file is read on opening. 2000 lines of a typical
# server's output is far less; a log nothing capped can be gigabytes, and
# reading it all to keep the tail would stall the panel.
INITIAL_BYTES = 2 * 1024 * 1024

_READ_CHUNK = 64 * 1024

# How long a stopped journal reader gets after SIGTERM before SIGKILL.
STOP_WAIT_SECONDS = 2.0

# CSI (colours, cursor moves), OSC (window titles, ended by BEL or ST), and any
# other two-character escape. Then every C0 control but tab, and DEL.
_ESCAPES = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b[@-_]?"
)
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

# The reasons a follower gives up, as facts rather than sentences: the panel
# composes the words, so they stay translatable (the controller's
# `action_done` makes the same split).
UNREADABLE = "unreadable"
NO_JOURNAL = "no-journal"
JOURNAL_ENDED = "journal-ended"


def _clean(line: str) -> str:
    """One line as a plain-text view should show it.

    A carriage return redraws a line in place on a terminal, so a progress bar
    is the text after the last one. Escapes go before the length cap, so the
    cap counts what is shown.
    """
    line = line.rstrip("\r").rsplit("\r", 1)[-1]
    line = _CONTROLS.sub("", _ESCAPES.sub("", line))
    if len(line) > MAX_LINE_CHARS:
        line = line[: MAX_LINE_CHARS - 1] + "…"
    return line


class LogBuffer:
    """The last `max_lines` complete lines, and the fragment after them."""

    def __init__(self, max_lines: int = MAX_LINES) -> None:
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._partial = ""
        # Incremental, so a character split across two reads decodes whole.
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def feed_bytes(self, data: bytes) -> list[str]:
        return self.feed(self._decoder.decode(data))

    def feed(self, text: str) -> list[str]:
        """Add `text`; return the lines it completed, cleaned, in order."""
        pieces = (self._partial + text).split("\n")
        self._partial = pieces.pop()
        added = [_clean(piece) for piece in pieces]
        self._lines.extend(added)
        return added

    def flush(self) -> list[str]:
        """Release a fragment no newline has followed.

        Called once a source has gone quiet: a server's last words are often
        written with no newline, and holding them for one would hide them for
        ever.
        """
        if not self._partial:
            return []
        line = _clean(self._partial)
        self._partial = ""
        self._lines.append(line)
        return [line]

    def lines(self) -> list[str]:
        return list(self._lines)


@dataclass(frozen=True)
class LogSource:
    """Where one project's output is read from.

    `unit` wins when set: a service-managed project has no log file of ours
    (ADR-0003). Neither set means there is nowhere to read — a window built
    with no supervisor. `output_unavailable` is design.md's `running
    (foreign)` case: the running server's output goes somewhere this app
    cannot see, though the file may still hold earlier output.
    """

    file: Path | None = None
    unit: str | None = None
    output_unavailable: bool = False


def journal_argv(unit: str) -> list[str]:
    """`journalctl --user -u <unit> -f`, ADR-0003's logs row.

    `--unit=<unit>`, glued, rather than `systemctl`'s `-- <unit>`: `-u` takes
    `--` as its own argument and the unit then becomes a journal match, which
    journalctl refuses (measured 2026-11-05, systemd 261). Glued, a name
    beginning with `-` is the option's value and never an option of its own;
    `valid_unit_name` refuses such a name as well.

    `--output=cat` shows the message alone, as the log file does.
    """
    if not valid_unit_name(unit):
        raise ValueError(f"refusing to read {unit!r}: not a unit name")
    return [
        "journalctl",
        "--user",
        f"--unit={unit}",
        "--follow",
        f"--lines={MAX_LINES}",
        "--output=cat",
        "--no-pager",
    ]


TextSink = Callable[[bytes], None]
ErrorSink = Callable[[str, str], None]


class _Follower:
    """A daemon thread with a stop flag, the shape both followers share."""

    def __init__(self, on_text: TextSink, on_error: ErrorSink) -> None:
        self._on_text = on_text
        self._on_error = on_error
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._guarded, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _guarded(self) -> None:
        # A plain thread prints an escaping exception and dies silently; the
        # panel would then wait for output for ever. Report it instead.
        try:
            self._run()
        except Exception as exc:
            log.exception("the log follower stopped")
            self._on_error(UNREADABLE, str(exc))

    def _run(self) -> None:
        raise NotImplementedError

    def _join(self) -> None:
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(STOP_WAIT_SECONDS + 1.0)


class FileFollower(_Follower):
    """Follow one of our own log files: read its tail, then what is added.

    Opened through `_open_private_regular`, the discipline every log of ours
    has: a symlink, a hard link, a FIFO or a file of another user's at the
    path is refused, never followed (LWSM-1049). The open is retried while the
    file does not exist, so a panel opened before the first start shows it.

    Two things change a file under a follower. `Supervisor.rotate_if_needed`
    truncates it IN PLACE, so a size below the offset means "start again from
    the top". Something replacing it changes the inode, so the path is
    reopened. What was already read stays in the ring either way.
    """

    def __init__(
        self,
        path: Path,
        on_text: TextSink,
        on_error: ErrorSink,
        *,
        interval: float = POLL_SECONDS,
        initial_bytes: int = INITIAL_BYTES,
    ) -> None:
        super().__init__(on_text, on_error)
        self._path = Path(path)
        self._interval = interval
        self._initial_bytes = initial_bytes

    def stop(self) -> None:
        self._stopping.set()
        self._join()

    def _open(self) -> int | None:
        try:
            return _open_private_regular(self._path, os.O_RDONLY)
        except FileNotFoundError:
            return None

    def _run(self) -> None:
        fd: int | None = None
        offset = 0
        try:
            while not self._stopping.is_set():
                if fd is None:
                    try:
                        fd = self._open()
                    except OSError as exc:
                        self._on_error(UNREADABLE, os.strerror(exc.errno or errno.EIO))
                        return
                    if fd is not None:
                        offset = self._first_offset(fd)
                if fd is not None:
                    offset = self._read_from(fd, offset)
                    if self._replaced(fd):
                        os.close(fd)
                        fd = None
                        continue
                self._stopping.wait(self._interval)
        finally:
            if fd is not None:
                os.close(fd)

    def _first_offset(self, fd: int) -> int:
        """Where to start: the top, or the first whole line of the tail."""
        size = os.fstat(fd).st_size
        if size <= self._initial_bytes:
            return 0
        start = size - self._initial_bytes
        head = os.pread(fd, self._initial_bytes, start)
        newline = head.find(b"\n")
        return size if newline < 0 else start + newline + 1

    def _read_from(self, fd: int, offset: int) -> int:
        size = os.fstat(fd).st_size
        if size < offset:
            offset = 0  # truncated in place by a rotation
        while offset < size and not self._stopping.is_set():
            chunk = os.pread(fd, min(_READ_CHUNK, size - offset), offset)
            if not chunk:
                break
            offset += len(chunk)
            self._on_text(chunk)
        return offset

    def _replaced(self, fd: int) -> bool:
        try:
            now = os.stat(self._path, follow_symlinks=False)
        except FileNotFoundError:
            return True
        held = os.fstat(fd)
        return (now.st_dev, now.st_ino) != (held.st_dev, held.st_ino)


Popen = Callable[..., subprocess.Popen[bytes]]


class JournalFollower(_Follower):
    """Follow a systemd user unit's journal through `journalctl`.

    Its own session (`§ O4`): it outlives the call that starts it, and is
    stopped by `stop()`, never left behind. stderr is merged so a reader that
    cannot open the journal says why in the panel.
    """

    def __init__(
        self,
        unit: str,
        on_text: TextSink,
        on_error: ErrorSink,
        *,
        popen: Popen | None = None,
    ) -> None:
        super().__init__(on_text, on_error)
        self._argv = journal_argv(unit)
        self._popen = popen if popen is not None else subprocess.Popen
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    def _run(self) -> None:
        with self._lock:
            if self._stopping.is_set():
                return
            try:
                process = self._popen(
                    self._argv,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                self._on_error(NO_JOURNAL, str(exc))
                return
            self._process = process
        stdout = process.stdout
        if stdout is None:  # cannot happen with stdout=PIPE; a fake may omit it
            self._on_error(NO_JOURNAL, "no output pipe")
            return
        fd = stdout.fileno()
        while True:
            chunk = os.read(fd, _READ_CHUNK)
            if not chunk:
                break
            self._on_text(chunk)
        code = process.wait()
        if not self._stopping.is_set():
            self._on_error(JOURNAL_ENDED, str(code))

    def stop(self) -> None:
        with self._lock:
            self._stopping.set()
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(STOP_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self._join()
        if process is not None and process.stdout is not None:
            process.stdout.close()


class LogFeed(QObject):
    """One project's source, followed into a `LogBuffer`, as Qt signals.

    Lines reach `lines_added` on the thread this object lives on — the GUI
    thread — because the follower's callbacks emit a private signal connected
    QUEUED. The ring is touched only there, so it needs no lock.

    A fragment left without a newline is flushed after one quiet tick, so a
    server's last words show even when it died mid-line.
    """

    lines_added = Signal(list)
    # (reason, detail): one of the module's reason constants, and what the
    # system said.
    failed = Signal(str, str)
    # Bytes, not text: a read can end inside a multi-byte character, and the
    # ring's incremental decoder is what puts it back together.
    _text = Signal(object)
    _error = Signal(str, str)

    def __init__(
        self,
        source: LogSource,
        parent: QObject | None = None,
        *,
        interval: float = POLL_SECONDS,
        popen: Popen | None = None,
    ) -> None:
        super().__init__(parent)
        self.source = source
        self.buffer = LogBuffer()
        self._interval = interval
        self._popen = popen
        self._follower: FileFollower | JournalFollower | None = None
        self._text.connect(self._on_text, Qt.ConnectionType.QueuedConnection)
        self._error.connect(self._on_error, Qt.ConnectionType.QueuedConnection)
        # Restarted by every read, so it fires only once the source has been
        # quiet for two ticks.
        self._quiet = QTimer(self)
        self._quiet.setSingleShot(True)
        self._quiet.setInterval(max(1, int(interval * 2000)))
        self._quiet.timeout.connect(self._flush)

    def start(self) -> None:
        source = self.source
        if source.unit is not None:
            self._follower = JournalFollower(
                source.unit, self._text.emit, self._error.emit, popen=self._popen
            )
        elif source.file is not None:
            self._follower = FileFollower(
                source.file, self._text.emit, self._error.emit, interval=self._interval
            )
        else:
            return
        self._follower.start()

    def stop(self) -> None:
        follower, self._follower = self._follower, None
        self._quiet.stop()
        if follower is not None:
            follower.stop()

    def _flush(self) -> None:
        released = self.buffer.flush()
        if released:
            self.lines_added.emit(released)

    def _on_text(self, data: bytes) -> None:
        added = self.buffer.feed_bytes(data)
        if added:
            self.lines_added.emit(added)
        self._quiet.start()

    def _on_error(self, reason: str, detail: str) -> None:
        self._flush()
        self.failed.emit(reason, detail)
