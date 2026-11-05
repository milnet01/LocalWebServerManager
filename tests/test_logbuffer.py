"""LWSM-1015 — following a project's output into a bounded ring.

The core half of the log panel: the ring, the two followers (a log file of
ours, or a systemd unit's journal) and the Qt bridge that hands lines to the
GUI thread. No widget here, so every behaviour is tested without a display
(`docs/standards/coding-overrides.md § O1`).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from lwsm.logbuffer import (
    MAX_LINE_CHARS,
    MAX_LINES,
    ErrorMatcher,
    FileFollower,
    JournalFollower,
    LogBuffer,
    LogFeed,
    LogSource,
    journal_argv,
)

# Follow the file quickly in tests; the real interval is a quarter-second.
FAST = 0.02


def wait_for(predicate, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for the follower")


class Collected:
    """What a follower handed over, from whichever thread it ran on."""

    def __init__(self) -> None:
        self.data: list[bytes] = []
        self.errors: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def on_text(self, data: bytes) -> None:
        with self._lock:
            self.data.append(data)

    def on_error(self, kind: str, detail: str) -> None:
        with self._lock:
            self.errors.append((kind, detail))

    def joined(self) -> str:
        with self._lock:
            return b"".join(self.data).decode()


# --- the ring ----------------------------------------------------------------


def test_the_ring_keeps_the_newest_lines_and_drops_the_oldest() -> None:
    """design.md § Observability: "the last N lines (default 2000)". Both
    halves at once — the bound, and WHICH end goes — so a ring that kept the
    first N, or kept everything, fails here."""
    ring = LogBuffer()
    ring.feed("".join(f"line {n}\n" for n in range(MAX_LINES + 5)))

    lines = ring.lines()
    assert MAX_LINES == 2000
    assert len(lines) == MAX_LINES
    assert lines[0] == "line 5"
    assert lines[-1] == f"line {MAX_LINES + 4}"


def test_a_line_is_held_until_it_ends_and_flush_releases_it() -> None:
    """A read can stop mid-line. Showing the half would split one line in two;
    holding it for ever would hide a last line written with no newline, which
    is exactly how a crashing server's final words often arrive."""
    ring = LogBuffer()
    assert ring.feed("Traceback (most") == []
    assert ring.feed(" recent call last):\n  File") == [
        "Traceback (most recent call last):"
    ]
    assert ring.flush() == ["  File"]
    assert ring.lines() == ["Traceback (most recent call last):", "  File"]
    assert ring.flush() == [], "a flushed fragment was released twice"


def test_terminal_escapes_and_control_characters_are_removed() -> None:
    """npm and most dev servers colour their output. Shown literally in a
    plain-text view, an escape sequence is noise a magnifier user has to read
    past; a carriage return redraws a progress line in place on a terminal."""
    ring = LogBuffer()
    lines = ring.feed(
        "\x1b[32mready\x1b[0m in 40 ms\r\n"
        "\x1b]0;title\x07plain\x07 bell\n"
        "10%\r50%\r100%\n"
        "tab\tkept\n"
    )
    assert lines == ["ready in 40 ms", "plain bell", "100%", "tab\tkept"]


def test_a_line_longer_than_the_cap_is_cut_with_an_ellipsis() -> None:
    """design.md § Detection rules: the LogPanel elides at the canonical
    per-line limit, so one number governs every untrusted string."""
    ring = LogBuffer()
    (line,) = ring.feed("x" * (MAX_LINE_CHARS * 3) + "\n")
    assert MAX_LINE_CHARS == 4096
    assert len(line) == MAX_LINE_CHARS
    assert line.endswith("…")


def test_invalid_utf8_is_replaced_rather_than_dropping_the_read() -> None:
    ring = LogBuffer()
    assert ring.feed_bytes(b"caf\xe9 ok\n") == ["caf� ok"]


def test_a_character_split_across_two_reads_is_decoded_whole() -> None:
    """A read boundary can fall inside a multi-byte character."""
    ring = LogBuffer()
    encoded = "naïve\n".encode()
    cut = encoded.index(b"\xc3") + 1
    assert ring.feed_bytes(encoded[:cut]) == []
    assert ring.feed_bytes(encoded[cut:]) == ["naïve"]


# --- the journal argv --------------------------------------------------------


def test_the_journal_argv_names_the_unit_so_it_cannot_be_read_as_an_option() -> None:
    """ADR-0003's verb table, logs row: `journalctl --user -u <unit> -f`.

    The unit goes in `--unit=<unit>`, glued to its option. `-u -- <unit>`, the
    `systemctl` shape, does not work here: measured 2026-11-05 on systemd 261,
    `-u` takes `--` as its argument and the unit becomes a journal match,
    which fails ("Failed to add match"). Glued, a name beginning with `-` is
    the option's value and cannot become an option of its own."""
    assert journal_argv("web.service") == [
        "journalctl",
        "--user",
        "--unit=web.service",
        "--follow",
        f"--lines={MAX_LINES}",
        "--output=cat",
        "--no-pager",
    ]


@pytest.mark.parametrize("unit", ["-H", "--host=evil", "", "a b.service"])
def test_the_journal_argv_refuses_a_name_that_is_not_a_unit(unit: str) -> None:
    with pytest.raises(ValueError, match="not a unit name"):
        journal_argv(unit)


# --- following a file -------------------------------------------------------


def follow_file(path: Path, collected: Collected, **kwargs) -> FileFollower:
    follower = FileFollower(
        path, collected.on_text, collected.on_error, interval=FAST, **kwargs
    )
    follower.start()
    return follower


def test_the_file_follower_reads_what_is_there_then_what_is_added(tmp_path) -> None:
    log = tmp_path / "web.log"
    log.write_text("before\n")
    collected = Collected()
    follower = follow_file(log, collected)
    try:
        wait_for(lambda: "before\n" in collected.joined())
        with log.open("a") as out:
            out.write("after\n")
        wait_for(lambda: collected.joined() == "before\nafter\n")
    finally:
        follower.stop()
    assert not follower.is_alive()


def test_the_file_follower_waits_for_a_file_that_does_not_exist_yet(tmp_path) -> None:
    """A project that has never been started has no log yet. The panel opens
    on it anyway, and the first start must appear without reopening it."""
    log = tmp_path / "web.log"
    collected = Collected()
    follower = follow_file(log, collected)
    try:
        time.sleep(FAST * 5)
        assert collected.errors == [], "a missing file is not an error"
        log.write_text("first start\n")
        wait_for(lambda: collected.joined() == "first start\n")
    finally:
        follower.stop()


def test_the_file_follower_carries_on_after_the_log_is_rotated(tmp_path) -> None:
    """`Supervisor.rotate_if_needed` copies the file aside and TRUNCATES it in
    place, keeping the inode, because the child holds a duplicate of our
    descriptor. A follower holding its offset would wait for the file to grow
    past the old size and show nothing until it did."""
    log = tmp_path / "web.log"
    log.write_text("x" * 500 + "\n")
    collected = Collected()
    follower = follow_file(log, collected)
    try:
        wait_for(lambda: collected.joined().endswith("x\n"))
        with log.open("r+") as out:
            out.truncate(0)
        time.sleep(FAST * 5)
        with log.open("a") as out:
            out.write("after rotation\n")
        wait_for(lambda: collected.joined().endswith("after rotation\n"))
    finally:
        follower.stop()


def test_the_file_follower_reads_only_the_tail_of_a_large_file(tmp_path) -> None:
    """A log left uncapped can be gigabytes; reading it all to keep the last
    2000 lines would stall the panel. Only the tail is read, and the line the
    cut falls inside is dropped rather than shown half."""
    log = tmp_path / "web.log"
    with log.open("w") as out:
        for n in range(200):
            out.write(f"line {n:03d}\n")
    collected = Collected()
    follower = follow_file(log, collected, initial_bytes=95)
    try:
        wait_for(lambda: collected.joined().endswith("line 199\n"))
    finally:
        follower.stop()
    text = collected.joined()
    assert text.startswith("line 1"), f"a cut line was shown: {text[:12]!r}"
    assert len(text) <= 95
    assert "line 000" not in text


def test_the_file_follower_never_follows_a_symlink(tmp_path) -> None:
    """The log directory is ours, but a symlink planted at a log's name would
    show any file this user can read in the panel. `_open_private_regular`
    refuses it (LWSM-1049: logs open with `O_NOFOLLOW`)."""
    secret = tmp_path / "secret.txt"
    secret.write_text("password=hunter2\n")
    log = tmp_path / "web.log"
    log.symlink_to(secret)
    collected = Collected()
    follower = follow_file(log, collected)
    try:
        wait_for(lambda: collected.errors)
    finally:
        follower.stop()
    assert "hunter2" not in collected.joined()
    assert collected.errors[0][0] == "unreadable"


# --- following a journal ----------------------------------------------------


def fake_journal(script: str):
    """A `popen` that runs a Python one-liner in place of `journalctl`."""
    import subprocess

    def popen(argv, **kwargs):
        popen.argv = argv
        popen.kwargs = kwargs
        return subprocess.Popen([sys.executable, "-c", script], **kwargs)

    return popen


def test_the_journal_follower_streams_the_reader_and_stops_it(tmp_path) -> None:
    popen = fake_journal(
        "import sys, time\nprint('Started web.service.', flush=True)\ntime.sleep(60)\n"
    )
    collected = Collected()
    follower = JournalFollower(
        "web.service", collected.on_text, collected.on_error, popen=popen
    )
    follower.start()
    try:
        wait_for(lambda: "Started web.service.\n" in collected.joined())
    finally:
        follower.stop()
    assert not follower.is_alive()
    assert popen.argv == journal_argv("web.service")
    # `coding-overrides.md § O4`: a child that outlives the call starting it
    # gets its own session; stdin is closed so it can never wait on us.
    assert popen.kwargs["start_new_session"] is True
    assert popen.kwargs["stdin"] is not None
    assert collected.errors == [], "a stop we asked for is not an error"


def test_a_journal_reader_that_ends_on_its_own_is_reported() -> None:
    popen = fake_journal("import sys; print('No journal files.'); sys.exit(1)")
    collected = Collected()
    follower = JournalFollower(
        "web.service", collected.on_text, collected.on_error, popen=popen
    )
    follower.start()
    try:
        wait_for(lambda: collected.errors)
    finally:
        follower.stop()
    assert "No journal files.\n" in collected.joined()
    assert collected.errors == [("journal-ended", "1")]


def test_a_missing_journalctl_is_reported_not_raised() -> None:
    def popen(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "journalctl")

    collected = Collected()
    follower = JournalFollower(
        "web.service", collected.on_text, collected.on_error, popen=popen
    )
    follower.start()
    try:
        wait_for(lambda: collected.errors)
    finally:
        follower.stop()
    assert collected.errors[0][0] == "no-journal"


# --- the Qt bridge ----------------------------------------------------------


@pytest.mark.gui
def test_the_feed_delivers_lines_on_the_gui_thread(qtbot, tmp_path) -> None:
    """`coding-overrides.md § O2`: the follower's thread never touches a
    widget, so the lines must arrive on the thread the feed lives on."""
    log = tmp_path / "web.log"
    log.write_text("one\ntwo\n")
    feed = LogFeed(LogSource(file=log), interval=FAST)
    seen: list[tuple[list[str], bool]] = []
    feed.lines_added.connect(
        lambda lines: seen.append(
            (list(lines), threading.current_thread() is threading.main_thread())
        )
    )
    feed.start()
    try:
        qtbot.waitUntil(lambda: feed.buffer.lines() == ["one", "two"], timeout=3000)
    finally:
        feed.stop()
    assert seen and all(on_main for _lines, on_main in seen)


@pytest.mark.gui
def test_the_feed_keeps_the_tail_after_the_server_has_gone(qtbot, tmp_path) -> None:
    """Criterion 5: a server that dies on startup is diagnosable without a
    terminal. Its file outlives it, so a feed opened afterwards still shows
    the last words, a partial final line included."""
    log = tmp_path / "web.log"
    log.write_text("Traceback (most recent call last):\nOSError: port in use")
    feed = LogFeed(LogSource(file=log), interval=FAST)
    feed.start()
    try:
        qtbot.waitUntil(
            lambda: feed.buffer.lines()[-1:] == ["OSError: port in use"],
            timeout=3000,
        )
    finally:
        feed.stop()
    assert feed.buffer.lines()[0] == "Traceback (most recent call last):"


@pytest.mark.gui
def test_a_source_with_neither_file_nor_unit_starts_nothing(qtbot) -> None:
    """A window with no supervisor has no log directory to name."""
    feed = LogFeed(LogSource())
    feed.start()
    feed.stop()
    assert feed.buffer.lines() == []


# --- LWSM-1036: which lines look like errors ----------------------------------


def test_the_usual_markers_find_the_usual_error_lines() -> None:
    """The four markers the roadmap names, as the runtimes print them."""
    matcher = ErrorMatcher()
    for line in (
        "Traceback (most recent call last):",
        "2026-11-05 10:00:01 ERROR app: database is locked",
        "CRITICAL: worker died",
        "java.lang.IllegalStateException: closed",
    ):
        assert matcher.matches(line), line
    for line in ("GET / 200", "Listening on port 5005", "0 errors, 0 warnings"):
        assert not matcher.matches(line), line


def test_a_marker_is_matched_as_written_never_as_a_pattern() -> None:
    """User input: `.` is a full stop, `(` is a bracket, and the case is the
    case typed. A regex reading would let `a.b` match `axb`, and a hostile
    pattern hang the panel."""
    matcher = ErrorMatcher(("a.b", "(x+x+)+y", "Fatal"))
    assert matcher.matches("saw a.b here")
    assert not matcher.matches("saw axb here")
    assert matcher.matches("literal (x+x+)+y")
    assert not matcher.matches("x" * 4000)
    assert not matcher.matches("fatal: lower case is not the marker")


@pytest.mark.parametrize(
    "line",
    [
        "Process finished with exit code 1",
        "server exited with code 3",
        "subprocess returned non-zero exit status 2.",
        "web.service: Main process exited, code=exited, status=1/FAILURE",
        "EXIT STATUS: 127",
    ],
)
def test_a_non_zero_exit_line_counts_even_with_no_markers(line: str) -> None:
    """Built in rather than a marker: "non-zero" is a number test, which a
    literal substring cannot express."""
    assert ErrorMatcher(()).matches(line)


@pytest.mark.parametrize(
    "line",
    [
        "Process finished with exit code 0",
        "web.service: Main process exited, code=exited, status=0/SUCCESS",
        "GET /health status 500",
        "exit codes are documented in README",
    ],
)
def test_a_clean_exit_or_an_http_status_is_not_an_error(line: str) -> None:
    """An HTTP status is a number after `status`, and the commonest line a web
    server prints; only an EXIT status counts."""
    assert not ErrorMatcher(()).matches(line)


def test_the_default_markers_are_the_settings_defaults() -> None:
    """One owner for the default set: `settings.py`, which may not import Qt."""
    from lwsm.settings import DEFAULT_ERROR_MARKERS

    assert ErrorMatcher().markers == DEFAULT_ERROR_MARKERS
