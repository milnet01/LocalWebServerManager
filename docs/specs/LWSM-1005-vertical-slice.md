# LWSM-1005 — Render one hand-written project as a live status row

**Status:** accepted (2026-08-06)
**Kind:** implement.
**Source:** ROADMAP LWSM-1005 (P02 vertical slice, in-session-2026-08-03).

**Blocked by:** LWSM-1001 (shipped — `src/lwsm/__main__.py::main`).
**Blocker for:** LWSM-1006, LWSM-1007, LWSM-1009, LWSM-1011.

**Layman:** One project you list by hand shows up in a window with a
coloured dot and the word *running* or *stopped*, and the dot follows
reality within two seconds.

## 1. Goal

After this ships, `lwsm` opens a window listing the projects named in a
hand-written `projects.json`, and each row states — as a word, a glyph and
a colour — whether anything is listening on that project's port, or reads
`unknown` where the project names no port to listen on. The label
follows the live socket table within 2 seconds of a server starting or
stopping, and survives an app restart because it is re-derived rather than
remembered. No scanner, no start button: the deliverable is that the wiring
from file to socket table to pixel is real and tested end to end.

## 2. Problem

The app has no UI and no core. `src/lwsm/__main__.py::main` parses
arguments, configures `src/lwsm/applog.py::configure_logging`, prints where
it logs to and returns 0 — verified by reading both files. Nothing in the
tree imports `PySide6` or `psutil`, though both are pinned in
`pyproject.toml` (`rg -c 'PySide6|psutil' src tests` → no matches), and
`docs/design.md § Components` names eleven components of which zero exist
(`awk '/^## Components/,/^## Detection rules/' docs/design.md | grep -c '^- \*\*'`
→ `11`).

Three consequences:

1. **Every later phase's contract is unvalidated.** `docs/design.md
   § Data flow` mandates one socket-table snapshot per tick shared across
   all projects, and `docs/standards/coding.md § O1` mandates a core that
   never imports `QtWidgets`. Both are prose until something is built to
   them.
2. **`projects.json` has a described record but no reader.** ADR-0005 lists
   the fields and requires a `schema_version` check; nothing parses it, so
   the "refused rather than partially parsed" rule has never run.
3. **`pytest-qt` and the `gui` / `integration` markers are declared and
   unexercised** (LWSM-1059). `scripts/local-ci.sh` already exports
   `QT_QPA_PLATFORM=offscreen`, so the headless lane exists and has never
   carried a test.

## 3. Scope decisions (and who made each)

- **Two states, and the collapse is deliberate.** The roadmap bullet asks
  for `running` and `stopped` only. With no `Supervisor` there is never an
  "own child", so only ADR-0004's last three table rows can fire, and this
  spec's `running` is the union of ADR-0004's `running (foreign)` and
  `port blocked`. The discriminator between them is the plausibility test
  (does the holder's exe or cwd lie under the project directory), which
  ADR-0004 calls a display heuristic with no security value — and nothing in
  P02 is gated on it, because P02 has no Start button to refuse. LWSM-1011
  splits the two. §5 INV-6 and §9 keep the collapse visible rather than
  silent.
- **Accessibility lands with the first row, not after.** Roadmap bullet's
  wording, and `docs/standards/coding.md § O8`. All four of O8's
  requirements apply to the row from the first commit.
- **A third status, `unknown`, where no observation is available.**
  Author's call, not the user's, and it is a reading of
  "two states" rather than a departure from it: `running` and `stopped`
  remain the only two states *derived from observation*, and `unknown` is
  what a row shows when there is no port to observe — the same word
  `docs/design.md § The effective port` uses for the same condition.
  Calling such a row `stopped` would be the one thing `§ O5` forbids.
- **The probe goes on a worker in P02, not later.** Author's call;
  `docs/design.md § State management` requires it unconditionally. §8
  carries the full argument and the rejected alternative.
- **One palette, not six.** LWSM-1031 owns the theme set; P02 needs
  widgets that name tokens rather than colours (§ O7), which one palette
  proves as well as seven.

## 4. Design

### 4.1 The record and the file

`~/.config/localwebservermanager/projects.json`, hand-written for P02.
Path is overridable for tests (`docs/standards/testing.md § T1`).

```json
{
  "schema_version": 1,
  "projects": [
    {"path": "/home/me/code/project-a", "name": "project-a", "port": 5005},
    {"path": "/home/me/code/project-b", "name": "project-b", "port": 5006,
     "port_override": 5106}
  ]
}
```

`src/lwsm/registry.py`, core, `QtCore` only:

```python
@dataclass(frozen=True)
class ProjectRecord:
    path: Path  # absolute, ADR-0005's identity
    name: str
    port: int | None  # declared; ADR-0005 "detected" half
    port_override: int | None  # user-owned half

    @property
    def effective_port(self) -> int | None: ...


class RegistryError(Exception): ...


def default_projects_path() -> Path:
    """$XDG_CONFIG_HOME/localwebservermanager/projects.json, falling back
    to ~/.config when the variable is unset or not absolute — the config
    half of `docs/standards/coding.md § O3`'s XDG rule, whose state half
    is already `applog.py::default_state_dir`."""


def load_projects(path: Path) -> tuple[list[ProjectRecord], list[str]]:
    """Returns (records, rejection messages). Raises RegistryError only
    when the file itself is unusable — see the four shapes below."""
```

Tests inject `path` directly, so no test reads the real config directory
(`§ T1`); `main` passes `default_projects_path()`.

`effective_port` is `port_override` if set, else `port`. That is the top
and third rungs of `docs/design.md § The effective port`; `confirmed_port`
(rung 2) arrives with LWSM-1038 and the framework default (rung 4) with
LWSM-1006, and until then a record with neither field reads `None`.

**The file is hand-editable, therefore attacker-editable** — ADR-0007's
reasoning about `settings.json`, applied here. `RegistryError` is raised,
and no records are returned, for four shapes — the file itself is unusable
and ADR-0005 forbids partially parsing it:

1. The file cannot be read: absent, a directory, permission denied, **not a
   regular file, or larger than `MAX_FILE_BYTES` (1 MiB)** — **any `OSError`**.
   Catching only `FileNotFoundError` would let the rest escape `main`, which
   §4.5 step 4 tolerates only `RegistryError` from.

   The read goes through a helper that opens with `O_RDONLY | O_NONBLOCK`,
   `fstat`s the descriptor and refuses anything that is not a regular file,
   then reads one byte past the cap so a file that grew between the two is
   still refused. Both halves were reproduced (LWSM-1072): a **FIFO** at the
   config path made `Path.read_bytes()` block forever — no window, no error,
   no log line, the least debuggable failure this app can have — and a 600 MB
   regular file peaked at **1214 MB RSS**. `applog.py` had already solved this
   class for `app.log`; `registry.py` did not get it. The helper is
   deliberately **weaker** than `applog._require_private_regular_file` and does
   not call it: that one also demands a single link and our own ownership,
   which is right for a log we write and wrong for a config file the user may
   reasonably hard-link or have installed for them.
2. The bytes are not valid UTF-8, are not valid JSON, or the top level is
   not an object. The first two are `ValueError` or narrower — and
   `UnicodeDecodeError` is **not** a `json.JSONDecodeError`, so it has to
   be named. **`json.loads` also raises two things that are neither**, both
   reproduced (LWSM-1072): a 5000-digit `port` hits CPython's 4300-digit
   integer-parse cap and raises a plain `ValueError`, and deeply nested arrays
   exhaust the stack and raise `RecursionError` — which is not a `ValueError`
   (it is `RecursionError → RuntimeError → Exception`), so `except ValueError`
   alone does not catch it. This sentence used to say `RecursionError` "is not
   an `Exception` at all", which is false; an implementer who believed it
   would widen a handler to `BaseException` and start swallowing
   `KeyboardInterrupt` (LWSM-1108). Both escaped as themselves past a caller that tolerates only
   `RegistryError`, so the app died with a traceback and no window. The clause
   is `except (ValueError, RecursionError)`, after the `JSONDecodeError` one
   because that subclasses `ValueError` and carries the more useful message. The third raises nothing at all: `json.loads` happily returns
   a list or a string, so it is an explicit `isinstance(data, dict)` check
   after a successful parse. An implementer who reads this as "wrap the
   parse in `except ValueError`" ships without it.
3. `schema_version` is absent, or is anything but the integer `1` —
   checked as `type(v) is int and v == 1`, because `True == 1` and a
   hand-edited `"schema_version": true` would otherwise pass.
4. `projects` is absent, or is not a list.

**A rejection reason is built with `repr` and clipped, never interpolated
raw** (LWSM-1078). The file is attacker-editable and a reason travels to two
places — `log.warning` in §4.5 and the status bar — so both properties are
load-bearing: `repr` escapes a newline, without which a project name forges
what reads as a second log record, and the clip bounds it, without which a
50 MB name produced a 50 MB status string. `MAX_REASON_CHARS` is 120.

**Three path shapes are refused rather than accepted or normalised**, all
reproduced:

- **`..` in any component.** `PurePath` keeps it, so `/srv/a` and
  `/srv/c/../a` compare unequal and *both* load — two records with one
  identity, which §6 calls a malformed file. Refused rather than lexically
  normalised, because collapsing `..` is wrong when a component is a symlink,
  and P03 passes this path as a spawn `cwd`.
- **A doubled leading slash.** The same hole in a second form, and it survived
  the fix above (LWSM-1103). POSIX gives *exactly* two leading slashes an
  implementation-defined meaning and `PurePosixPath` preserves them as a
  distinct root — `Path('//srv/a').parts == ('//', 'srv', 'a')` — while
  `realpath` resolves both to the same directory, so `/srv/a` and `//srv/a`
  both loaded with no reason recorded. Three or more slashes collapse;
  exactly two do not. Verified clean in the same sweep and therefore not
  re-searched: a trailing slash, `///`, `.` components and `/srv/a/.`.
- **A NUL byte.** It passes `is_absolute()` and loads, though every later `os`
  call on it raises `ValueError`.

**The status bar needs no `PlainText` call, and this was checked rather than
assumed.** The P02 review held that `statusBar().showMessage(...)` leaves Qt's
`AutoText` free to render markup, unlike the row labels which set `PlainText`
explicitly. Measured against the pinned PySide6 6.11.1: `QStatusBar` has no
child `QLabel` and paints the message through `style()->drawItemText`, which is
plain-text only. Rendering `<b>bold</b>` drew **508** ink pixels against **232**
for `bold` — the markup is drawn literally. That quarter of the finding is
**dismissed as unverified**; the other three were real and are fixed above.

Each **element** of `projects` that is not a JSON object is skipped with a
reason — it has no fields to check, and indexing it would raise a
`TypeError` that shape 2 does not cover. Every field of every surviving
record is then type-checked before use:

| Field | Accepted | Why that range |
|---|---|---|
| `path` | non-empty `str`, absolute, **free of `..` and of NUL bytes**, unique within the file | ADR-0005 makes the absolute path the identity; a duplicate would give two rows one identity |
| `name` | non-empty `str` | it is the row's label and the accessible name |
| `port` | absent, `null`, or an `int` 1–65535 | the *declared* half. A project that genuinely declares 80 or 443 is legitimate data, so ADR-0005's 1024–65535 floor does **not** apply here — that floor governs the override |
| `port_override` | absent, `null`, or an `int` 1024–65535 | ADR-0005: "an override is validated at entry against the same 1024–65535 range ADR-0002 requires" |

**`bool` is not accepted for either port field**, though
`isinstance(True, int)` is `True` in Python (verified on 3.13). On an
attacker-editable file a naive `isinstance(v, int)` accepts `"port": true`
and yields port 1. The check is `type(v) is int`.

A record whose `path` or `name` fails is **skipped**, with its reason in
the second tuple element — there is nothing left to identify or label it
by. A record whose `port` or `port_override` fails **loads with that field
`None`**, also with a reason: the project still exists and the user still
needs to see it, and dropping the whole row would make a mistyped port look
like a deleted project. Surviving records always load, because one typo
must not blank the list.

### 4.2 The probe

`src/lwsm/ports.py`, core, no Qt at all:

```python
@dataclass(frozen=True)
class PortSnapshot:
    listening: frozenset[int]

    def is_bound(self, port: int) -> bool: ...


class SupportsSnapshot(Protocol):
    def snapshot(self) -> PortSnapshot: ...


class PortProbe:  # the real one; satisfies the Protocol
    def snapshot(self) -> PortSnapshot: ...
```

The `Protocol` is what `ProjectController` accepts, so the fake probes
INV-3, INV-11 and INV-12 inject are the declared contract rather than a
duck-typing workaround the annotation quietly contradicts.

`snapshot()` makes exactly one `psutil.net_connections(kind="tcp")` call
and keeps the `laddr.port` of every entry whose status is
`psutil.CONN_LISTEN` **and whose `laddr` is truthy**; an entry with a falsy
`laddr` is skipped. One call per tick for the whole list, never one per
project — `docs/design.md § Data flow`. Port ownership (holder PID, exe,
cwd) is deliberately absent: P02 asks only *is anything listening*, and
adding the holder lookup would be implementing LWSM-1011 early.

**Anything** the call raises is caught and re-raised as `ProbeError`, with
the original kept as `__cause__`, so the poll loop has one exception type to
handle and a partial socket table never reads as an empty one.

The clause is `except Exception`, not `except psutil.Error`. An earlier
revision of this section claimed `psutil.Error` was the whole surface on the
strength of `issubclass(psutil.AccessDenied, psutil.Error)` → `True`; the
subclass check is correct and the conclusion drawn from it was not.
`psutil`'s own `_pslinux.process_inet` parses `/proc/net/tcp` unguarded, so a
malformed line raises a bare `RuntimeError`, and hidepid, an LSM or a
`/proc`-less container raise `OSError` — and neither `issubclass(RuntimeError,
psutil.Error)` nor `issubclass(OSError, psutil.Error)` holds (both `False`,
verified against the pinned 7.2.2). Naming a library's declared exception base
is not the same as enumerating what it can raise. Corrected under LWSM-1069.

That `laddr` guard is belt-and-braces: on this machine no listening entry
has a falsy `laddr` (0 of 12, measured), but the field is typed as possibly
empty and a probe that raised `AttributeError` mid-tick would take the poll
down.

### 4.3 The poll

`src/lwsm/controller.py`, core, `QtCore` only:

```python
POLL_INTERVAL_MS = 1000


class ProjectStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RowView:  # everything one row renders
    path: Path
    name: str
    effective_port: int | None
    status: ProjectStatus


class ProjectController(QObject):
    projects_changed = Signal()  # docs/design.md § State management

    def __init__(
        self,
        records: list[ProjectRecord],
        probe: SupportsSnapshot,
        parent: QObject | None = None,
    ) -> None: ...
    def start_polling(self) -> None: ...
    def stop(self) -> None: ...  # timer off, wait for the pool
    def poll_once(self) -> None: ...
    def rows(self) -> list[RowView]: ...
```

`rows()` is the only thing `MainWindow` reads, and it carries everything a
row renders. A bare `dict[Path, ProjectStatus]` would force the window to
keep its own copy of the records to find each row's name and port, which
`docs/design.md § Components` forbids — "it holds no state of its own
beyond widget state". Order is the file's order, so rows do not jump.

**Three statuses, not two.** `RUNNING` and `STOPPED` are the two derived
states the roadmap bullet asks for. `UNKNOWN` is not a third derived state:
it means **no observation is available**, and covers exactly two cases —
a record with no `effective_port`, so there is no port to look at; and any
record for which no *successful* poll has yet completed, since the probe is
asynchronous and `start_polling()` returns before its result arrives, and a
first poll that raised `ProbeError` completed without observing anything.
Calling either `stopped` would assert something nobody looked at (`§ O5`).
`docs/design.md § The effective port` uses the same word for the first case
— "one with nothing at all is *unknown*" — and the second is the same
absence for a different reason.

**The probe runs off the controller's thread**, which is the thread `main`
constructs everything on and therefore the one owning `MainWindow`. This
document calls it the **owning thread** throughout.
`docs/design.md § State management` is unconditional — "the socket-table
probe runs on a worker so a slow `psutil` call cannot freeze the window" —
and `§ O2` requires a worker to reach the UI **only** through a queued
signal. §8 records why this lands in P02 rather than later.

So `poll_once` does not probe. It submits a task to
`QThreadPool.globalInstance()`:

```python
class _SnapshotSignals(QObject):
    done = Signal(object)  # carries a PortSnapshot
    failed = Signal(object)  # carries a ProbeError


class _SnapshotTask(QRunnable):
    def __init__(self, probe: SupportsSnapshot) -> None:
        super().__init__()
        self.signals = _SnapshotSignals()

    def run(self) -> None: ...  # called on the pool thread
```

**The signals live on a composed `QObject`, not on the task**, because
`QRunnable` is not a `QObject`: `issubclass(QRunnable, QObject)` → `False`
under the pinned PySide6 6.11.1, and a `Signal` declared directly on a
plain `QRunnable` subclass raises `AttributeError: 'PySide6.QtCore.Signal'
object has no attribute 'emit'` when emitted. Both verified by running
them, not by recall — `§ O6`: "check an API exists in the installed PySide6
before designing around it."

For the record, so nobody re-litigates it: `class _SnapshotTask(QObject,
QRunnable)` **also** works under 6.11.1 — it instantiates, connects, runs
on a pool thread and emits, checked with `QObject.__init__(self)` and
`QRunnable.__init__(self)` called explicitly. The composed signaller is
chosen anyway, because it is the shape PySide6's own documentation uses and
it keeps the auto-delete question below off a multiply-inherited object.

**The signaller belongs to the controller, not to the task**, and is created
once. The task keeps the pool's default auto-delete, so it is freed as soon as
`run()` returns.

This was `setAutoDelete(False)` with a signaller per task, on the reasoning
that the pool would otherwise free the task while a queued emission was still
in flight. The emission needs its **signaller** to survive, not its task — and
`QThreadPool.start()` transfers ownership to C++, so with auto-delete off
nothing on the Python side could free a task at all: 200 live `_SnapshotTask`
and 200 live `_SnapshotSignals` after 200 completed polls, about 210 MiB/day
at the 1000 ms interval, plus a connection list growing behind every retained
signaller (LWSM-1099). Moving the signaller up is what lets auto-delete stay
on. The controller holds a `_in_flight` flag rather than the task, because a
reference to an auto-deleted task outlives its C++ object.

**Shutdown is part of the contract, and it has four parts** (LWSM-1073,
LWSM-1098, LWSM-1100). `ProjectController.stop()` sets `_stopped`, stops the
`QTimer`, and waits on its **own** pool for at most `STOP_WAIT_MS`; `run()` —
not `main()` — then ends the process if a probe was abandoned.

- **`_stopped` is checked in the slots, and disconnecting cannot replace it.**
  `waitForDone` waits for `run()` to *return*, but the emit happens inside
  `run()` over a queued connection — so by the time it returns the event is
  already posted, and it is dispatched on the next event-loop spin into a
  controller that has been torn down. `mainwindow.py` connects that signal, so
  the late delivery re-enters the window's widgets after teardown. Reproduced:
  zero emissions immediately after `stop()` returned, one after a single spin.

  Cutting the connections in `stop()` was the first fix and closed only the
  window it was measured against: Qt dispatches a `QMetaCallEvent` that has
  already been **posted** regardless of any later disconnect, so a probe
  finishing just *before* `stop()` still delivered (LWSM-1098). The flag is
  what holds, and it also guards `poll_once`, which was otherwise free to
  re-arm delivery after shutdown.
- **The pool is private, not `QThreadPool.globalInstance()`.** Waiting on the
  global pool makes this controller's shutdown block on every unrelated
  runnable in the process — including the per-project reader threads
  `docs/design.md § State management` already plans. Reproduced: with one
  unrelated runnable in flight, `stop()` took **5.00 s**. One thread, since a
  tick arriving mid-probe is skipped rather than queued.
- **The wait is bounded** at `STOP_WAIT_MS` (2000 ms; measured probe time is
  33.4 ms mean, so ~60x headroom). An unbounded wait turns a probe that never
  returns into an app that cannot be quit, which §6 does not promise — it
  promises a stale display. This is a **shutdown** budget, not a watchdog:
  nothing times out into a *state*, so ADR-0004's "slowness is not failure"
  is untouched.

When the budget expires, the pool is moved to a module-level list so it is not
destroyed: `~QThreadPool` calls `waitForDone()` with no timeout, so letting it
go would reintroduce at teardown exactly the hang the budget bounds.

**That defers the hang rather than removing it, and the second half is what
bounds it** (LWSM-1100). CPython releases module globals at interpreter
shutdown, which destroys those pools and runs that unbounded wait: measured,
`stop()` returned in 0.10 s and the process took **4.16 s** to exit behind a
4 s probe. There is no Qt-level way to cancel a running `QRunnable` or to stop
`~QThreadPool` waiting, so the only thing that bounds it is declining to run
the destructor — `exit_without_waiting_for_abandoned_probes` `os._exit`s after
flushing, and only while an abandoned pool still holds a thread.

**That call lives in `run()`, not in `main()`,** and the split is load-bearing
rather than tidiness. Tests call `main()` in-process, and an earlier test
abandons a probe; with the exit inside `main()` the pytest run ended at 40 % of
the suite **with exit code 0** and a truncated report that read as green.
Anything that ends the process belongs behind the console-script entry point.

`stop()` is idempotent — `main` calls it and so does every test
fixture. `main` calls it after `app.exec()`
returns, and every test fixture calls it in teardown — `§ T5` ("every test
kills what it started") covers pool threads as much as sockets, and a task
emitting into a half-torn-down controller is the shape that makes a suite
flaky in a way that reproduces once a week.

The controller connects `done` and `failed` on the owning thread before
submitting, so both are queued, and classifies in those slots.
Classification touches no OS state, so it is cheap and belongs where the
signal lands.

**Nothing may escape `run()`.** Its final clause is `except BaseException`,
which emits `failed` carrying a `ProbeError` that wraps whatever was raised,
and logs it with a traceback. The clause is as wide as the language allows
rather than as wide as the failures anyone predicted, because the escape path
is not a crash: an exception leaving `QRunnable.run()` is **swallowed by
PySide6** — verified against the pinned 6.11.1 — so the traceback prints to
stderr, the process survives at exit 0, and **no signal is emitted**. The
in-flight flag below is therefore never cleared, and the poll loop stops for
the life of the process while the window goes on showing plausible, frozen
data. A worker whose failure mode is silent permanence is worse than one that
crashes, so this is the one place in the codebase where a bare catch-all is
the correct construct rather than a workaround. Added under LWSM-1069.

**A tick whose predecessor is still in flight is skipped, not queued** —
`docs/design.md § Data flow`, verbatim: "the poll skips a tick rather than
queueing". One `_in_flight` flag, cleared in both slots.

`start_polling()` calls `poll_once()` **immediately** and then starts the
`QTimer`, so the window is populated at once rather than blank for the
first second.

**The first completed poll emits `projects_changed` unconditionally**, via
a `_emitted_once` flag — *not* by comparing status maps. Deriving it from
map inequality fails on the case INV-15 exercises: with zero records the
map is empty before and after, so nothing "differs" and the window would
never be told to render its empty state. This holds whether the first poll
succeeded or failed in any way; INV-4b's no-emit rule applies from the
second poll on, because before the first there is no previous value to
hold and a blank window would otherwise never update.

Subsequent ticks emit `projects_changed` **only when at least one status
differs from the previous tick**. Suppressing the no-change emission is
what `docs/design.md § Accessibility` requires of a state change announcing
itself once rather than on every poll; it is also why the interval can stay
at 1 s without the screen reader chattering.

A `ProbeError` is handled as §6 describes; §6 is canonical for it.

Worst-case latency to a visible flip is one interval plus probe time.
Measured probe time on this machine is **33.4 ms mean over 10 calls**
(`uv run python -c "import time,psutil; t=time.perf_counter();
[psutil.net_connections(kind='tcp') for _ in range(10)];
print((time.perf_counter()-t)/10*1000)"` → `33.4`), against the ≤250 ms
budget in `docs/design.md § Data flow`, so 1000 + 33 ms sits inside the
2-second criterion with room.

### 4.4 The row

`src/lwsm/theme.py` (UI layer) carries a frozen `Theme` of the nine base
tokens `docs/design.md § Tokens, not colours` adopts from finbreak —
`window`, `base`, `alt_base`, `text`, `muted_text`, `accent`,
`accent_soft`, `attention`, `border` — plus `is_dark`, plus three state
tokens: `state_running`, `state_stopped` and `state_unknown`. One default
palette; `Theme` expands to a `QPalette` and a generated style sheet.

**`state_running` is provisionally bound and will be re-pointed.** In
`docs/design.md § Tokens, not colours` the seven state tokens are one per
ADR-0004 derived state, so `state_running` means `running (managed)` — a
state P02 can never observe, since there is no `Supervisor`. P02 renders
its collapsed `running` (§3) with `state_running` because that is the token
whose *name* matches the word on screen; when LWSM-1011 lands the seven
states, rows re-point to `state_foreign` and `state_blocked` and the four
remaining tokens arrive with LWSM-1031's palettes. That re-point is one
line in one widget, and it is recorded in §9 so it is a scheduled change
rather than a surprise. `state_unknown` is likewise P02-local: ADR-0004 has
no `unknown` state because it lists states derived from *observation*, and
`UNKNOWN` is the absence of anything to observe.

`src/lwsm/mainwindow.py` (UI layer):

```python
class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: ProjectController,
        theme: Theme,
        notices: list[str],
        parent: QWidget | None = None,
    ) -> None: ...
    def set_status_message(self, text: str) -> None: ...
```

`notices` is `load_projects`'s second tuple element — the per-record
rejection reasons — and `set_status_message` is what §6 and INV-15 mean by
"reaches the status bar". §4.5 routes both: the rejection list into the
constructor, and a `RegistryError`'s own message through the same slot.
Without these two the plumbing for a behaviour INV-15 tests would have to
be invented by the implementer.

**N notices become one status-bar line**: the first, then `(+N more)` when
there is more than one — the bar is one line and a join would truncate
unpredictably. **Every notice is logged in full**, one line each at
WARNING, by `build_window`, so the status bar is a summary and the log is
the record. `Theme.default()` supplies the single palette; it is the light
one, since that is what a first run gets with no settings file to say
otherwise.

It builds one row widget per `RowView` **once**, and on each
`projects_changed` **updates the existing widgets in place** — the changed
rows' text and tokens only. `_sync_rows` calls `update_from` on *every* row on
*every* signal, so "the changed rows only" is enforced inside `update_from` by
an equality check against the `RowView` it last rendered, which returns
immediately when nothing differs. `RowView` is a frozen dataclass, so the
comparison is free. Without it only `QLabel::setText` short-circuits;
`setStyleSheet`, `setAccessibleName` and the announcement below do not
(LWSM-1076). It does not rebuild the list. Rebuilding would
destroy and recreate every row widget on any one
project's flip, which discards keyboard focus (`docs/design.md
§ Accessibility`: "the app never steals focus") and re-announces every
*unchanged* row to a screen reader — undoing at the widget level exactly
what the signal-level suppression in §4.3 achieves. Rows are only created
or destroyed when the record list itself changes, which in P02 is never.

Each row is, in visual and tab order:

| Cell | Content |
|---|---|
| state | a **painted glyph** (`●` running / `○` stopped / `?` unknown) in a reserved leading column, then a label holding the **word** `running` / `stopped` / `unknown`. Both take the matching state token's colour |
| name | the project's display name |
| port | `port 5005` — the word and the number — or the literal `no port` |

The port cell carries the **word** `port`, not a bare number, because
`docs/design.md § Accessibility` gives the announcement as "project-b,
running, port 5005" and the cell text is what a screen reader reads. A bare
`5005` would leave a listener with an unlabelled number.

**The glyph is decorative and is excluded from the accessible name.** It
is one of the three signals `docs/design.md § Accessibility` requires, and
it carries nothing the word does not — so a screen reader that read it
would announce "black circle, running, project-a", which is noise wearing
the costume of redundancy. `state_text` below means **the word alone**.

**Excluding it means painting it, not naming it "" — and the difference is
the whole of LWSM-1071.** An earlier revision said the glyph sub-label was
"marked accessibility-ignored", and the code implemented that as
`setAccessibleName("")`. That call does not hide anything: `QAccessibleDisplay`
falls back to `QLabel::text()` when the accessible name is empty, so the row
exposed **four** children and child 0 was named `'●'` — verified by querying
the live interface. Qt Widgets has no "ignored" flag to set (Qt Quick's
`Accessible.ignored` has no widget equivalent), so the only way to keep
something out of the tree is for it not to be a widget. The glyph is therefore
drawn in `ProjectRow.paintEvent` into a leading column reserved by widening the
layout's left content margin, and `Theme.state_color()` expands the token for
it because `§ O7` forbids the widget from constructing a colour.

Two things this costs, both deliberate: the painted glyph needs an explicit
`update()` in `update_from`, since nothing else marks the row dirty; and a test
that only checks the AT tree would pass just as well if the glyph had been
**deleted**, so INV-19 checks the pixels too.

**All slack sits after the last cell, not inside one.** The row's layout ends
in a stretch, so widening the window leaves the three cells grouped at the left
at their natural widths. Giving the *name* cell the stretch instead put every
spare pixel inside that label, and `QLabel` aligns left by default — so the name
stayed where it was while the port was pinned to the right edge. Measured at
1400 px before the fix: name text at x=84, port text at x=1333.
`docs/design.md § Accessibility` names that shape outright ("never name on the
far left and state on the far right, which forces a pan and a memory test"), and
LWSM-1032's own acceptance is that every cell falls inside a 600 px-wide window
— which the stretched-name layout failed at any width above it (LWSM-1074).

The state cell is first, which `docs/design.md § Accessibility` requires
("the state word is first in the row"). Each row is a focusable widget
whose accessible name is built **from the rendered cell strings, in their
visual order, glyph excluded** —
`f"{state_text}, {name_text}, {port_text}"`, giving
`"running, project-a, port 5005"` and `"unknown, project-b, no port"`.
The order differs from the design's example sentence because the design
separately requires the state word first in the row; the *content* is the
same three facts. Building the name from the cells rather than from the
model is what makes `docs/design.md § Accessibility`'s "no separate
accessibility-only string to drift" literally true, and it is why no row
can announce `port None`.

**A changed row raises an accessibility event; `setAccessibleName` alone does
not.** Qt does not notify AT-SPI when an accessible name changes, so
`docs/design.md § Accessibility`'s promise that "a state change announces
itself once" was unimplemented — the name was correct and no screen reader was
ever told it had changed. `update_from` now raises a
`QAccessibleEvent(self, QAccessible.Event.NameChanged)` after updating.

The two halves are one fix, not two: adding the announcement *without* the
equality check above turns a once-a-second no-op into a once-a-second
re-announcement of every unchanged row — the failure INV-13 exists to prevent,
arriving by another route. Verified by removing the check: the
never-re-announced test goes red.

`QAccessible.installUpdateHandler`, the seam Qt provides for observing these,
is **not exposed in PySide6** (checked against the pinned 6.11.1) and AT-SPI is
not reachable headless, so the tests count the call itself. That is a weaker
surface than this document prefers, and it is the strongest one available.

**Every user-visible string in this file goes through
`QCoreApplication.translate`** under one context, per `coding.md § 5.2`
(LWSM-1081). Three decisions came with it, each recorded because each is a
choice rather than a wrapper:

- **The status words get a UI-side display map, not a wrapped enum.** They come
  from a core `StrEnum` that the UI rendered with `str()`; translating them by
  wrapping the enum would put user-visible text in a core module. `state_word()`
  is that seam.
- **`%1`, substituted with `str.replace`, not `str.format`.** A translation is
  data from outside the program: one that dropped or misspelled a `{port}`
  field would raise inside a signal handler, which is LWSM-1082's crash class
  by another route. `replace` cannot raise, so a bad translation loses the
  number rather than the window. Found by a test translator that mangled the
  placeholder.
- **Log messages and the `argparse` text are deliberately NOT translated.**
  Logs are read by whoever is debugging and should match the source; and
  translating the CLI text needs Qt imported before `argparse` runs, which
  INV-14 forbids.
- **A `LanguageChange` branch retranslates the rows**, and translating at call
  time is not enough on its own. Three gaps went with that assumption, all
  three verified by running (LWSM-1107): the status bar's `(+N more)` was an
  f-string and reached no translator at all; the window title used `self.tr`,
  which resolves under the *class* — so it landed in `"MainWindow"` (and Qt
  then walked `QMainWindow`, `QWidget`, `QObject`, `QPaintDevice`) rather than
  the one context this file declares; and a translator installed **after** the
  window was built never reached an existing row, because LWSM-1076's equality
  guard suppresses the only path that would re-render. `ProjectRow.retranslate`
  clears the held view so that guard cannot swallow it.

  **What is pinned here is the handler, not Qt's delivery.** Measured against
  the pinned PySide6 6.11.1, with the loop running and the window the only
  registered top-level widget: `installTranslator` returned `True` and Qt did
  **not** post `LanguageChange` to it, while a bare `QMainWindow` in the same
  shape did receive it. Unexplained, and out of this project's hands. No
  user-visible impact in P02, which has no language switcher; a switcher
  installs the translator itself and can send the event.

  The status bar is deliberately **not** re-derived on a language change:
  `build_window` may have replaced the notice summary with a `RegistryError`,
  and re-applying the summary would silently overwrite it.

Nothing sets a colour literal, a font family or a pixel size: colours come
from tokens, sizes from the text metric (`§ O7`).

**The colour rules come from `Theme.style_sheet()`, not from widget code**
(LWSM-1077). `docs/design.md § Tokens, not colours` gives a `Theme` two
outputs — a `QPalette` **and** a generated style sheet, finbreak's two-layer
split — and only the palette existed, so this file hand-built
`f"color: {token};"` and called `setStyleSheet` per row per tick. INV-8b still
passed, because there was no colour *literal*; the layer the design asked for
was simply missing and its job had leaked one level down.

The sheet selects on a dynamic property (`Theme.STATE_PROPERTY`), so it is a
constant of the theme: set once on the window, and a row changing state sets a
property rather than composing CSS. **The widget must then be re-polished** —
Qt does not re-evaluate a style-sheet selector when the property it matches on
changes, so without it the word keeps the colour it was last polished with.

`to_palette()` also sets `Button`, `ButtonText`, `HighlightedText`,
`ToolTipBase` and `ToolTipText`, which were left at the style default — P05's
buttons and tooltips would not have followed the theme.

**A focused row paints a focus ring, and the row paints it itself.** `QFrame`
renders only its frame and `StyledPanel` never consults `State_HasFocus`, so
setting `StrongFocus` alone produced a widget that took focus and showed
nothing — the focused and unfocused renders were byte-identical and Tab moved
an invisible caret (LWSM-1070). `coding.md § O8` clause 2 requires a visible
focus ring, `docs/design.md § Accessibility` calls it the thing a magnifier
user's "where am I?" depends on entirely, and WCAG 2.4.7 requires it.

`ProjectRow.paintEvent` draws it: a rectangle inset by half its pen width, in
the colour `Theme.focus_ring_color()` returns. Three consequences worth
stating, because each was a decision:

- **The ring is the `accent` token**, not a token of its own, so every palette
  LWSM-1031 adds inherits a legible ring from the contrast its accent already
  has to prove. Measured on the default palette: **5.42:1** against `window`,
  against the **3:1** floor `testing.md § T8` sets for a non-text indicator.
- **The theme expands the token into a `QColor`, not the widget.** `§ O7`
  forbids widget code from naming a colour or constructing one, which
  `tests/test_layering.py` enforces by regex — so the expansion belongs at the
  definition site.
- **The pen width comes from the text metric** (`fontMetrics().height() / 8`,
  floored at one device pixel), never a constant. A fixed width would thin to a
  hairline under LWSM-1032's 200 % text-size control — the setting the users
  who depend on the ring are likeliest to be running.

### 4.5 The entry point

`src/lwsm/__main__.py::main` today configures logging, then prints two
lines — `lwsm <version> — no interface yet (P02 builds it).` followed by
`Logging to <path>` (or `Not logging to a file.`) — and returns 0; read,
not recalled. P02 replaces **the `no interface yet` line** with the window.
**The `Logging to …` line stays**: `CLAUDE.md § Module map` records
printing the log destination as deliberate behaviour, and it is how a user
finds the log when the window misbehaves.

1. `argparse` runs first and is untouched, so `--version` and `--help` still
   exit without constructing a `QApplication` and therefore work with no
   display.
2. Logging is configured exactly as now, including the stderr fallback.
3. `QApplication` is constructed, and then **all the wiring happens in a
   separate function**:

   ```python
   def build_window(
       projects_path: Path | None = None,
   ) -> tuple[MainWindow, ProjectController]:
       """Load, construct and connect. Does not run an event loop."""
   ```

   `projects_path` defaults to `None`, meaning **resolve it inside this
   function**, and that default is load-bearing rather than a convenience.
   `default_projects_path()` can raise `RegistryError` — it has guarded
   `Path.home()` since LWSM-1026 — and while `main` called
   `build_window(default_projects_path())` the argument was evaluated *before*
   the call, so the only catch written for that exception could not see it. On a
   machine with no home directory the app died with a traceback and no window
   (LWSM-1116). A fallible default belongs inside the boundary that handles it.

   `build_window` calls `load_projects(projects_path)`, then `PortProbe`,
   `ProjectController`, `MainWindow(controller, Theme.default(), notices)`
   — `notices` being `load_projects`'s rejection list — and
   `controller.start_polling()`. `main` then calls `window.show()`,
   `app.exec()`, and `controller.stop()`, and returns `app.exec()`'s value.

   **The split is what makes step 4 testable.** `main` ends in a blocking
   `app.exec()`, so an in-process test can never reach a catch that lives
   inside it; a test that constructed `MainWindow` itself would be testing
   the window and not the catch. `build_window` runs no event loop, so
   INV-15 drives it directly. `main` is left as three lines with nothing
   in it worth a test beyond INV-14.

4. A `RegistryError` is **caught in `build_window`** and is not fatal: the
   window is constructed with no records and an empty `notices`, and
   `set_status_message(...)` names the file and the reason (§6).
   `start_polling()` still runs — a project list that failed to load does
   not stop the poll from establishing that there is nothing to poll, and
   INV-5's zero-record case depends on it. A missing `projects.json` must
   not stop the app from starting, for the same reason an unwritable log
   does not. No other exception is caught here — a bug must not be
   disguised as a first run.

`QApplication` is constructed inside `main`, never at module import, so
importing `lwsm.__main__` in a test does not require a display.

## 5. Invariants

- **INV-1** — `load_projects` raises `RegistryError`, and returns no
  records, for each of the four unusable-file shapes §4.1 enumerates:
  unreadable (any `OSError`), not-UTF-8/not-JSON/not-an-object,
  `schema_version` absent or not the integer `1`, and `projects` absent or
  not a list. §4.1 is canonical for the four; this clause does not restate
  their detail.
  *Test:* `tests/test_registry.py::test_unusable_files_are_refused`, one
  parametrised case per shape — including a chmod-000 file and a
  non-UTF-8 one, which the two commonest hand-written implementations
  (`FileNotFoundError` only, `json.JSONDecodeError` only) both let escape.
  *Breaks when:* a file carrying `"schema_version": 2`, or none at all, is
  parsed for its `projects` key anyway.

- **INV-2** — A `projects` element that is not a JSON object is skipped
  with a reason, and so is a record whose `path` or `name` is absent, not a
  string, or the empty string, or whose `path` duplicates one already
  loaded or is not absolute. Every well-formed record in the same file
  still loads.
  *Test:* `tests/test_registry.py::test_bad_record_skipped_others_load`,
  with a case per rejection reason.
  *Breaks when:* `{"projects": [1, {"path": "/a", "name": "a"}]}` raises
  `TypeError` out of `load_projects` instead of skipping the `1`;
  `{"path": "", "name": "x"}` loads as a record; or two records sharing one
  `path` both load and then collapse into one row.

- **INV-3** — One `poll_once` calls `PortProbe.snapshot()` exactly once
  regardless of how many records are classified.
  *Test:* `tests/test_controller.py::test_one_snapshot_per_poll`, a
  counting fake probe over 10 records.
  *Breaks when:* the snapshot moves inside the per-record loop — the shape
  that turns a 33 ms tick into a 330 ms one at ten projects.

- **INV-3b** — One `PortProbe.snapshot()` makes exactly one
  `psutil.net_connections` call. INV-3 alone cannot see this: its fake
  probe never reaches `psutil`, so without this clause the one-call-per-tick
  claim is only half tested.
  *Test:* `tests/test_ports.py::test_one_net_connections_call_per_snapshot`,
  with `psutil.net_connections` monkeypatched to a counter.
  *Breaks when:* `snapshot()` calls `net_connections` once per address
  family, or re-reads to resolve holders.

- **INV-4** — On any tick whose probe **succeeded**, every status is
  derived from that snapshot alone. The single sanctioned carry-over is the
  failed-probe hold in INV-4b.
  *Test:* `tests/test_controller.py::test_status_is_rederived_not_remembered`
  — **two ticks on one controller**: drive it to `RUNNING` with a snapshot
  containing the port, then feed a snapshot without it and assert
  `STOPPED`. A fresh controller is not a valid fixture here: having no
  previous status, it reports `RUNNING` under a sticky implementation too,
  so that shape cannot fail for the breach it names.
  *Breaks when:* a previous status is consulted on a *successful* tick
  rather than only as the change-detector — which is how `§ O5` gets
  breached quietly.

- **INV-4b** — From the second completed poll onward, a tick whose probe
  failed **in any way** leaves every status at its previous value and does
  not emit `projects_changed`. The **first** completed poll is exempt and
  emits either way (INV-5): before it there is no previous value to hold,
  and suppressing it would leave the window at its blank initial state
  forever.
  *Test:* `tests/test_controller.py::test_probe_error_holds_previous_status`,
  with a case for a failing *first* poll asserting it still emits, and
  `::test_a_held_status_survives_an_unexpected_exception` for a probe that
  raises something no clause names.
  *Breaks when:* a failed probe is treated as an empty snapshot, which
  reports every project `stopped` on the strength of a `psutil` error — a
  state nobody observed, and the worse of the two failures because it looks
  like news.
  *Scope note (LWSM-1069):* this said "raised `ProbeError`" until the P02
  close, which made the invariant unfalsifiable against the failure that
  actually shipped — an exception no clause named never reached a slot at
  all, so no status was held, nothing was emitted, and the invariant was
  satisfied by the loop having stopped.

- **INV-4c** — A probe raising an exception the poll loop does not name
  leaves the loop still polling: the tick after such a failure issues a
  probe, and a later successful probe updates the statuses.
  *Test:* `tests/test_controller.py::test_an_unexpected_exception_does_not_wedge_the_poll_loop`
  and `::test_the_loop_recovers_once_the_probe_does`; the failure is
  asserted visible by `::test_an_unexpected_exception_is_reported_not_silent`.
  *Two layers, not one:* the emit can fail as well as the probe. A task
  abandoned by `stop()`'s budget outlives the `QApplication` that owned every
  other `QObject`, so its signaller can be destroyed before it finishes and
  `emit` raises `RuntimeError: Signal source has been deleted` — which
  escaped `run()` from *outside* the inner clause until LWSM-1073 found it.
  *Breaks when:* anything is allowed to escape `_SnapshotTask.run()`. PySide6
  swallows it, so the breach has no crash, no dialog, no status change and no
  log line — the window simply stops updating for the life of the process.
  Assert against a **later tick issuing a probe**, not against the process
  surviving: it always survives.

- **INV-5** — The first completed poll emits `projects_changed`
  unconditionally, **including when the record list is empty**; afterwards
  the signal is emitted on a tick whose statuses differ from the previous
  tick, and not on one whose statuses are identical.
  *Test:* `tests/test_controller.py::test_first_poll_emits_then_only_on_change`,
  including a zero-record case.
  *Breaks when:* the first emission is derived from comparing status maps
  rather than from a flag — with zero records the map is empty before and
  after, so nothing "differs" and the empty window is never rendered. Also
  when the emit is unconditional *thereafter*, which makes the screen
  reader re-announce every row once a second; or when the first poll is
  left to the timer, which leaves the window blank for a second.

- **INV-6** — Every state the row shows is present as text. Removing all
  colour and all glyphs from a row still leaves `running`, `stopped` or
  `unknown` readable.
  *Test:* `tests/test_mainwindow.py::test_state_is_a_word_not_only_colour`,
  asserting the row's visible text contains the status word, that its
  accessible name does too, and that the accessible name contains **none**
  of the glyph characters `●○?` — a name built from the raw state cell
  would announce "black circle, running, …".
  *Breaks when:* the dot becomes the only state signal — the red/green
  failure `docs/design.md § Accessibility` names as its commonest case.

- **INV-7** — A real server binding an OS-assigned port flips its row to
  `running` within 2 seconds, and closing it flips the row back.
  *Test:* `tests/test_mainwindow.py::test_row_follows_a_real_socket`,
  `qtbot.waitUntil(..., timeout=2000)` per `§ T3`, `§ T4`.
  *Breaks when:* the poll interval is raised past ~1900 ms, or the timer is
  never started.

- **INV-8** — No module in `registry`, `ports`, `controller` imports
  `QtWidgets`.
  *Test:* `tests/test_layering.py::test_core_never_imports_qtwidgets`.
  *Breaks when:* a `QMessageBox` is reached for inside the controller —
  the first thing that makes the core need a display.

- **INV-8b** — `src/lwsm/mainwindow.py` contains no colour literal — no
  `#rrggbb` string and no `QColor(`. `src/lwsm/theme.py` is the one
  exempted module: it is the token *definition* site, so the palette's
  values necessarily live there, and `§ O7`'s rule is about widget code.
  *Test:* `tests/test_layering.py::test_no_colour_literals_in_widget_code`,
  scanning the widget modules with `theme.py` excluded by an explicit
  allowlist rather than by the pattern happening to miss it.
  *Breaks when:* a widget hard-codes `#1e1e2e` for the running dot — which
  is invisible in one theme and unreadable in another.

- **INV-9** — A `PortSnapshot` contains a port at the moment a real socket
  is listening on it, and does not contain that port once the socket is
  closed.
  *Test:* `tests/test_ports.py::test_snapshot_follows_a_real_socket`, over
  a socket bound to port `0`.
  *Breaks when:* the status filter is dropped, so every *connected* socket's
  local port reads as listening too — which would make an outbound
  connection from an ephemeral port look like a running server.

- **INV-10** — A record with a `port` of `80` loads, with `port == 80`. A
  record with a `port_override` of `80` loads with `port_override is None`
  and a reason. Neither is dropped from the list.
  *Test:* `tests/test_registry.py::test_port_ranges_differ_by_field`.
  *Breaks when:* ADR-0005's 1024–65535 override floor is applied to the
  declared port, which deletes every project that legitimately declares 80
  or 443 — and deletes the *row*, so it reads as a project that does not
  exist rather than one with a port we will not accept. Also when
  `"port": true` is accepted, since `isinstance(True, int)` is `True` and a
  naive check turns it into port 1.

- **INV-11** — `PortProbe.snapshot()` is never invoked on the controller's
  owning thread. INV-3b carries the `psutil`-level half; this one is about
  where the call happens, and together they cover the rule. The invariant is
  stated against `snapshot()` rather than against `psutil.net_connections`
  because the fixture is a fake probe, and a claim about `psutil` would be
  one the test cannot see — the gap INV-3b exists to close for INV-3.
  *Test:* `tests/test_controller.py::test_probe_runs_off_the_owning_thread`,
  recording `threading.get_ident()` inside a fake `snapshot()` and
  asserting it differs from the ident recorded in the test body, which is
  the thread that constructed the controller.
  *Breaks when:* `poll_once` probes inline — a 33 ms UI stall every second
  today, and an unbounded one the first time `psutil` blocks, which is the
  freeze `docs/design.md § State management` puts the worker there to
  prevent.

- **INV-12** — A tick that fires while a probe is still in flight is
  skipped: two ticks with one slow probe outstanding produce one
  `snapshot()` call, not two.
  *Test:* `tests/test_controller.py::test_tick_skipped_while_probe_in_flight`.
  Because the probe is asynchronous, the assertion is made **after**
  `qtbot.waitSignal` on the outstanding task's completion (`§ T4`) — an
  assertion taken before either runnable has run would count one call and
  pass for the wrong reason. INV-3's counting test waits the same way.
  *Breaks when:* ticks queue instead — `docs/design.md § Data flow` says
  "the poll skips a tick rather than queueing", and queueing is how a
  briefly-slow socket table becomes a permanently-lagging one.

- **INV-13** — Row widgets are created once. A status change updates the
  existing widgets, and the widget that had keyboard focus still has it
  afterwards.
  *Test:* `tests/test_mainwindow.py::test_focus_survives_a_status_change`,
  focusing a row, driving a flip, asserting the focused widget is identical
  (`is`) to the one focused before.
  *Breaks when:* the layout is cleared and rebuilt per signal — which drops
  focus mid-read for a magnifier user and re-announces every unchanged row.

- **INV-14** — `lwsm --version` and `lwsm --help` exit 0 without
  constructing a `QApplication`, and therefore work with no display.
  *Test:* `tests/test_main.py::test_version_needs_no_display`, running the
  entry point in a subprocess with `QT_QPA_PLATFORM` unset and `DISPLAY` /
  `WAYLAND_DISPLAY` removed from the environment.
  *Breaks when:* `QApplication` is constructed at module import or before
  `parse_args` — which turns `--version` on a headless box into an abort.

- **INV-15** — A `RegistryError` does not stop the app: `build_window`
  returns a window with no rows whose status bar names the file and the
  reason, and does not raise.
  *Test:* `tests/test_mainwindow.py::test_registry_error_opens_an_empty_window`,
  calling `build_window` on a path with no file. It targets `build_window`
  rather than `main` because `main` blocks in `app.exec()`, so a test that
  called it would never return. `tests/test_main.py::test_starts_even_when_there_is_no_home_directory`
  covers the half that test cannot: it drives `main` with the event loop stubbed
  and asserts the window is **shown** with the reason in its status bar, which
  is the only way to observe a `RegistryError` raised by resolving the *default*
  path rather than by reading a given one.
  *Breaks when:* the exception propagates — a missing `projects.json` is
  first-run, not a crash, on the same reasoning that keeps an unwritable
  log from killing startup — **or** a fallible path resolution is moved back to
  `main`, where the argument is evaluated outside the catch (LWSM-1116).

- **INV-16** — After `ProjectController.stop()` returns, **no snapshot is
  ever delivered to the controller again**, `stop()` has not waited on work
  that is not its own, and it has returned within `STOP_WAIT_MS`.
  *Wording note (LWSM-1073):* this read "no task is outstanding" until the
  P02 close, and that sentence was **true while the invariant's stated
  purpose was being violated** — the task had indeed finished, and its queued
  emission was already posted and landed one spin later. An invariant phrased
  over the mechanism passes when the mechanism is intact; phrase it over the
  delivery.
  *Test:* `tests/test_controller.py::test_stop_waits_for_the_outstanding_task`,
  with a fake probe that blocks until released, plus
  `::test_no_snapshot_is_delivered_after_stop` (which lets the probe
  **complete** before `stop()` — gating it instead put the emit inside
  `waitForDone`, where the test could only catch "no disconnect at all" and not
  the "disconnect too late" that was actually shipping, LWSM-1098),
  `::test_a_poll_started_after_stop_delivers_nothing`,
  `::test_stop_does_not_wait_on_unrelated_work` (a blocker runnable on the
  global pool), `::test_stop_is_bounded_when_a_probe_never_returns` (asserted
  against the patched budget, not a 20x-loose literal) and
  `::test_the_process_exits_promptly_when_a_probe_is_abandoned`, which measures
  the **process** in a subprocess — every in-process assertion here passed
  while LWSM-1100 was live.
  *Breaks when:* `stop()` only stops the `QTimer` — the pool thread then
  emits into a controller the test has already dropped, which is the
  once-a-week flake `§ T5` exists to prevent.

- **INV-17** — A focused row renders differently from an unfocused one, and
  the ring's colour clears `testing.md § T8`'s 3:1 indicator floor against
  the window.
  *Test:* `tests/test_mainwindow.py::test_focus_is_visible_not_merely_held`,
  which grabs the row in both states and counts changed pixels, plus
  `tests/test_theme.py::test_the_focus_ring_clears_the_indicator_floor`.
  The pixel count is compared against the row's perimeter, so an
  antialiasing artefact cannot pass for a ring. Measured on the default
  palette: **858 of 6734 pixels** changed, ring width 2 px, contrast
  **5.42:1**.
  *Breaks when:* the ring is asserted by property rather than by rendering.
  `focusPolicy()`, `hasFocus()` and the accessible name were all already
  correct while the two renders were byte-identical — which is exactly how
  this shipped. Assert the pixels.
  *Fixture trap:* Qt gives focus to the first focusable widget when the
  window is shown, so the row is **already focused** at the point a test
  would take its baseline. A baseline grabbed without `clearFocus()` first is
  a focused render, and the comparison then reports "no ring" whether or not
  one is painted. `qtbot.waitExposed` and `qtbot.waitActive` are also context
  managers; called bare they wait for nothing, and an inactive window makes
  `hasFocus()` false.

- **INV-18** — Every token that renders as **text** clears `testing.md
  § T8`'s 4.5:1 against the surface it is painted on. The state tokens count
  as text pairs, not indicators: they colour the state *word*, not only the
  glyph. Measured on the default palette — `text` 15.63:1, `muted_text`
  6.21:1, `state_stopped` 6.21:1, `state_unknown` 4.79:1, `state_running`
  4.61:1.
  *Test:* `tests/test_theme.py::test_every_text_token_clears_the_text_floor`,
  parametrised over tokens **and** over themes, so the palettes LWSM-1031
  adds inherit the check and one that fails is a failing build.
  *Breaks when:* a palette is eyeballed. `state_unknown` shipped at
  **4.46:1** — a miss of 0.04 that no reviewer would catch by looking, in
  the palette a first run gets (LWSM-1075).
  *Guard:* `::test_the_contrast_formula_matches_published_values` pins the
  arithmetic to WCAG's published values first, because a miscomputed ratio
  passes every palette silently and that is indistinguishable from a clean
  one.

- **INV-19** — The row's accessibility tree contains exactly its three cells
  — `["running", "a", "port 5005"]` — and no glyph, while the glyph is still
  drawn on screen.
  *Test:* `tests/test_mainwindow.py::test_the_row_exposes_only_its_three_cells`
  and `::test_the_glyph_is_never_a_child_of_the_accessibility_tree`, plus
  `::test_the_glyph_is_still_painted_after_leaving_the_label`, which blanks
  the glyph and re-renders so the difference *is* the glyph.
  *Breaks when:* the assertion is made against the row's own accessible name.
  INV-6 does exactly that and **passes** — the name was always correctly
  `'running, demo, port 8080'` while a screen reader walking children found
  `'●'`. Assert against `childCount()` and each child's
  `text(QAccessible.Text.Name)`.
  *And breaks the other way:* every AT-tree assertion here would also pass if
  the glyph were simply removed from the UI, which would silently drop one of
  `design.md § Accessibility`'s three redundant signals. The pixel check is
  what stops the fix over-shooting into a regression.
  *Trap:* an exact-colour pixel match works for the filled `●` and fails for
  `○` and `?` — antialiased strokes contain no pixel equal to the pure token
  colour.

- **INV-20** — At any window width, every cell in a row falls inside a
  600 px band from the row's left edge, and the cells keep their order without
  overlapping.
  *Test:* `tests/test_mainwindow.py::test_the_row_stays_grouped_when_the_window_is_wide`
  at 1400 px, plus `::test_the_cells_keep_their_order_and_do_not_overlap`,
  which guards the obvious over-correction — removing the stretch could as
  easily have piled the cells on top of each other.
  *Breaks when:* a cell is given `stretch`. The slack lands inside that
  widget rather than after the row, and the visible result depends on that
  widget's alignment rather than on the layout — which is why it reads as
  correct in the code.

- **INV-21** — Every message carrying a hand-edited value contains no raw
  newline and is bounded in length, whatever the file contains. This covers the
  `RegistryError` messages as well as the per-record rejection reasons: a raised
  message reaches `log.warning` and `set_status_message` by the same route a
  reason does, and it was the clause saying "rejection reason" that let
  `schema_version` sit unbounded through two fixes of this mechanism
  (LWSM-1114).
  *Test:* `tests/test_registry.py::test_a_newline_in_a_name_cannot_forge_a_log_line`
  (asserts the newline survives **escaped** rather than being stripped, so the
  reason still says what was wrong), `::test_an_enormous_name_is_clipped`,
  `::test_the_clip_bounds_the_escaped_text_not_the_raw_text`,
  `::test_a_hostile_port_field_cannot_flood_the_reason`,
  `::test_a_hostile_schema_version_cannot_flood_the_error` and
  `::test_no_file_sourced_value_is_interpolated_without_the_clip` (the
  whole-module sweep, so the *next* call site is caught at the gate rather than
  by a fourth review).
  *Breaks when:* any hand-edited value is interpolated as `{value!r}` rather
  than through `_quoted`, **or** the clip is applied before the escape rather
  than after.

  This clause used to say `{value!r}` on the *port* fields "already did the
  right thing". Half true, and the false half is what made LWSM-1078 stop at
  the name and path: `repr` escapes but does not clip, so a 200 KB string in
  `port` produced a **200,038**-character reason against a constant of 120
  (LWSM-1102). Clipping before the escape was bounding the wrong string in the
  same way — 400 non-printable astral characters returned **1203**
  (LWSM-1111). Escaping and bounding are two properties; a clause naming one
  of them satisfied is not evidence about the other.

- **INV-22** — A row whose `RowView` changed raises exactly one accessibility
  `NameChanged` event; a row whose `RowView` did not raises none.
  *Test:* `tests/test_mainwindow.py::test_a_state_change_is_announced` and
  `::test_an_unchanged_row_is_never_re_announced`, the second driving
  `update_from` directly so the controller's own signal suppression cannot be
  what makes it pass.
  *Breaks when:* either half ships without the other. With no event, the name
  is right and nobody is told. With no equality check, every unchanged row is
  re-announced once a second.

- **INV-23** — Two rows in different states render their state word in
  different colours, and a row that *changed* into a state renders like one
  built in it.
  *Test:* `tests/test_mainwindow.py::test_the_state_word_takes_its_colour_from_the_status`
  and `::test_a_status_change_repaints_the_word_in_the_new_token`, both forcing
  **the same text** into both labels first — `running` and `stopped` differ in
  glyphs as well as colour, so an unforced comparison proves nothing about the
  colour.
  *Breaks when:* the re-polish after the property change is dropped. Recorded
  because it was dropped during LWSM-1077 on the strength of two tests that
  stayed green: one comparing a *freshly built* row (whose first polish is
  correct either way) and one comparing two rows that were both wrong in the
  same direction. A test that cannot distinguish "both right" from "both
  wrong" is the shape to watch for here.

- **INV-24** — A theme's `text` token is the colour a row's name and port cells
  are actually rendered in, not merely the colour the `QPalette` holds.
  *Test:* `tests/test_mainwindow.py::test_the_theme_reaches_the_cells_not_only_the_window`,
  under a **dark** theme, because under the default one the invariant cannot
  fail: Fusion's fallback black is darker than the `text` token, so the wrong
  colour has *better* contrast and nothing looks wrong. Antialiasing is switched
  off for the grab (`QFont.StyleStrategy.NoAntialias`) so the token can be
  asserted exactly — with it on, a name label rendered 0 pixels of a pure
  `#ff00ff` out of 119 and its ink spanned 40 colours including near-white
  subpixel fringe, which a first version of the test matched instead of the
  text.
  *Breaks when:* the palette is set on the **window** rather than on the
  **application**. `setStyleSheet` installs `QStyleSheetStyle`, which re-resolves
  every descendant from the application palette and discards the widget's own —
  so `to_palette()`'s 13 roles reached the frame and stopped. Measured before
  the fix: `window` at `WindowText=#1b1b1f` against the central widget, the row
  and all three cell labels at `#000000`, and a dark theme rendering the name
  and port at **1.25:1 and 1.27:1** against `§ T8`'s 4.5:1 floor — invisible,
  for a primary user who is partially sighted (LWSM-1118).

  `theme.py`'s claim that "tokens expand into a QPalette so native widgets
  follow the theme" was false for three reviews because the light default made
  the failure look like success. A palette assertion that does not render is not
  evidence about what a user sees.

- **INV-25** — Changing the **application** font reflows a row that already
  exists, not only rows built afterwards.
  *Test:* `tests/test_mainwindow.py::test_an_application_font_change_reflows_an_existing_row`,
  driving `QApplication.setFont` and asserting the glyph column and left margin
  both move.
  *Breaks when:* a test drives `row.setFont` instead. That is not a style note —
  it is how this stayed hidden. The window's style sheet makes
  `QStyleSheetStyle` resolve a font onto every descendant, marking it explicitly
  set, so an application font change reached the window and stopped: measured
  **zero** calls to `ProjectRow._apply_text_metrics` for both
  `QApplication.setFont()` and `MainWindow.setFont()`, against 1 for
  `row.setFont()`. Isolated against a bare `QWidget` tree, the same change
  delivers 1 `FontChange` with no style sheet and 0 with one. All three tests
  covering `§ O8` clause 4's 100-200 % path used `row.setFont`, so the suite
  reported the path as covered while the route a real text-size control takes
  was dead (LWSM-1119). `MainWindow.changeEvent` now pushes the window font down
  to the rows, the same shape as its `LanguageChange` branch and for the same
  reason.

## 6. Failure modes

- **`projects.json` absent.** `RegistryError`; the window opens empty with
  a status-bar line naming the path it looked at (INV-15). First run is not
  an error state until LWSM-1008 lands the scan-and-confirm flow.
- **`projects.json` unparsable, not an object, or missing / wrong
  `schema_version` or `projects`.** `RegistryError` naming the file and
  which of §4.1's four shapes it hit. Nothing is written back — P02 never
  writes the file at all.
- **A record is rejected, or one of its port fields is.** The reason
  reaches the status bar and the app log; the other rows render, and a
  record rejected only on a port field still renders with `no port`. Silent
  skipping would make a typo look like a deleted project.
- **Two records name the same `path`.** The second is skipped with a
  reason (INV-2). ADR-0005 makes the absolute path the identity, so two
  records with one identity is a malformed file, not a merge question.
- **The app quits while a probe is outstanding.** `main` calls
  `controller.stop()` after `app.exec()` returns, which stops the timer and
  blocks until the pool is idle (INV-16). Without it a pool thread emits
  into a controller being torn down during interpreter shutdown.
- **The socket table cannot be read.** `ProbeError`, logged at WARNING **on
  the first failure and then only when the message changes** (LWSM-1079);
  every row keeps its previous status and no signal is emitted (INV-4b).
  The poll is 1000 ms, so a permanently unreadable socket table — a hardened
  kernel, a persistent `AccessDenied` — wrote roughly **86,400 lines a day**
  into a handler that rotates at 1 MiB keeping 5, scrubbing away the history
  the user is told to consult. Suppressed **by message, not by count**: a
  different failure is news, and hiding it would be the over-correction. The
  suppressed count is reported when the message changes, when a poll succeeds,
  and on `stop()` — so silence and suppression are never indistinguishable.
  Reporting `stopped` on a failed probe would be reporting a state nobody
  observed (`§ O5`). This is the canonical statement of the behaviour; §4.3
  points here.
- **The project list is malformed in bulk.** `load_projects` keeps at most
  `MAX_REASONS` (100) rejection reasons and appends one tail naming how many
  more there were, on the same reasoning as the probe path above — the rule is
  the general one, not a property of probes, and applying it in only one of the
  two places is what LWSM-1112 is about. The registry path had the same
  amplification with a **worse** constant: the cheapest malformed element is two
  bytes, so a file at `MAX_FILE_BYTES` produced **524,271** reasons and
  **20,859,730** characters, which `build_window` wrote out as one
  `log.warning` each — **28.7 MB** through a handler that rotates at 1 MiB
  keeping 5. And unlike the probe path it is not spread over a day: it happens
  in one burst *before* `window.show()`, so it was **8.7 s of no window** with
  nothing on screen to interrupt. Measured before and after on 2026-08-07:
  524,271 reasons / 28.7 MB / 4.38 s of logging became 101 reasons / 5,153
  bytes / 1 ms (LWSM-1115).
- **The probe raises something nothing here anticipated.** Handled exactly as
  the line above, and deliberately not as a separate path: `PortProbe` wraps
  anything the socket-table read raises, and `_SnapshotTask.run()` wraps
  anything at all, both into a `ProbeError`. The unexpected case additionally
  logs a traceback, because unlike a routine `AccessDenied` it is a defect
  report. What it must never do is nothing — see §4.3 on PySide6 swallowing an
  exception that escapes `run()` (INV-4c).
- **The probe outlives its tick.** The next tick is skipped rather than
  queued (INV-12). A probe that never returns stops the status updating and
  leaves the last-known state on screen — visibly stale, rather than
  wrongly confident. No watchdog: nothing here may time out into a wrong
  state (ADR-0004 § Slowness is not failure).
- **The app quits while a probe is stuck.** `stop()` waits `STOP_WAIT_MS`
  and then abandons the pool, and `run()` — not `main()` — ends the process
  without waiting for it. Both halves are needed: abandoning alone only
  *defers* the wait, because the pool is destroyed at interpreter shutdown
  and `~QThreadPool` has no timeout. Measured at 4.16 s to exit behind a 4 s
  probe while `stop()` itself returned in 0.10 s (LWSM-1100). A stale display
  is promised here; an app that cannot be quit is not.
- **Something other than `run()` holds an abandoned pool at shutdown.** The
  clause above bounds the *app*, and for a while that was read as bounding the
  mechanism. It does not: `exit_without_waiting_for_abandoned_probes` is an
  `os._exit`, so only an entry point may call it, and every other process — the
  test suite, a future embedder, a reload path — inherited the wait in full
  (LWSM-1117). Such a caller must instead reach shutdown holding **nothing**:
  `wait_for_abandoned_probes(timeout_ms)` reaps the pools that have gone idle
  and returns how many have not.

  Two facts measured while closing it, both stronger than the report that
  raised it:

  - The wait is **unbounded**, not "about 3 s". A probe that genuinely never
    returns hung the interpreter indefinitely — killed at three minutes, main
    thread on a futex joining the pool thread. The suite's 2.6 s was 2.6 s only
    because its *fake* probe carries a 5 s timeout.
  - **No Python-level ownership trick avoids it.** Dropping the reference,
    holding it, reparenting it, and invalidating the Shiboken wrapper were each
    run against a truly stuck probe; all four hung identically. The C++
    destructor joins the thread regardless. This is why the only bound is
    declining to run the destructor, and why nothing here tries to cancel a
    running `QRunnable` — Qt offers no way to.

  A caller that neither exits nor reaps therefore still blocks, and that cannot
  be fixed from inside a core module: ending the process here would override an
  exit code this code cannot see, which is exactly LWSM-1100's failure. An
  `atexit` guard prints the reason to stderr first, so the hang is diagnosable
  rather than silent. It is a diagnosis, not a bound, and is documented as one.
- **Two records share a port.** Both rows read `running` off the same
  socket. ADR-0005 catches this at merge time, and there is no merge in
  P02 — LWSM-1007 owns it. Named here so a reviewer knows it was seen.
- **A server binds only IPv6, or only a non-loopback address.** The
  snapshot keys on port alone, so it is seen. This is deliberately looser
  than "the project is reachable at `localhost:<port>`"; the health check
  that closes that gap is LWSM-1034.

## 7. Tests

Five new test files, a new `tests/conftest.py`, plus one existing file —
all headless (`§ T6`; `scripts/local-ci.sh` already exports
`QT_QPA_PLATFORM=offscreen`, and the `conftest.py` sets it when unset so a
bare `pytest` cannot open a real window). INV-14's subprocess is the one
exception and **must not
inherit that value** — it removes `QT_QPA_PLATFORM`, `DISPLAY` and
`WAYLAND_DISPLAY` from the child's environment, because its whole claim is
that `--version` needs no platform plugin at all:

**Markers go on tests, not files.** `pyproject.toml` defines `integration`
as "spawns real child processes or binds real sockets" and `gui` as "needs
a Qt application object". Marking a whole file by its heaviest test means
`./scripts/local-ci.sh --fast` (`-m "not integration"`) silently drops
every light test that shares the file — which would have hidden the
accessibility, focus and empty-window invariants behind the one test that
binds a socket.

| Invariant | File | Marker |
|---|---|---|
| INV-1, INV-2, INV-10, INV-21 | `tests/test_registry.py` | — |
| INV-3b | `tests/test_ports.py` | — (monkeypatched counter; binds nothing) |
| INV-9 | `tests/test_ports.py` | `integration` |
| INV-3, INV-4, INV-4b, INV-4c, INV-5, INV-11, INV-12, INV-16 | `tests/test_controller.py` | `gui` (a `QTimer`, queued cross-thread signals and `QThreadPool` all need a Qt application object) |
| INV-6, INV-13, INV-15, INV-17, INV-19, INV-20, INV-22, INV-23 | `tests/test_mainwindow.py` | `gui` |
| INV-17 (contrast half), INV-18 | `tests/test_theme.py` | none — pure arithmetic, no display |
| INV-7 | `tests/test_mainwindow.py` | `gui`, `integration` |
| INV-8, INV-8b | `tests/test_layering.py` | — |
| INV-14 | `tests/test_main.py` (existing file) | `integration` (spawns a subprocess) |

INV-15 drives `build_window`, which constructs the window, so it lives with
the widget tests; INV-14 observes the entry point before any window exists,
so it lives in `test_main.py`.

Ports come from binding `0` and asking the socket, never a literal
(`§ T3`). Waits are `qtbot.waitUntil` on the condition, never a sleep
(`§ T4`). Every fixture closes its socket **and calls
`ProjectController.stop()`** in teardown (`§ T5`, INV-16) — a pool thread
outliving its test poisons the next one exactly as a leaked child process
would. No test reads the real `~/.config/localwebservermanager/` (`§ T1`).

Each test is seen to fail before its implementation lands, **against a stub
that exists and returns the wrong answer** — never against an absent
module. An `ImportError` is a collection error: it proves the module is
missing, which nobody doubted, and says nothing about whether the assertion
can fail. So each module is created first with signatures and a wrong or
empty return, the suite is run red, and only then is the body written.

## 8. Alternatives considered (and rejected)

- **Put the poll timer in `MainWindow`.** Fewer files, but the poll then
  needs a display to test, and `docs/design.md § Components` gives
  `MainWindow` no state beyond widget state. Rejected: it would make the
  one behaviour with a 2-second contract the one behaviour only a GUI test
  can reach.
- **Resolve the port holder's PID in P02.** It would let the row say
  `running (foreign)` versus `port blocked` honestly. Rejected: that is
  LWSM-1011's classifier arriving early, and it pulls in the plausibility
  test, the uid disclosure and the `psutil` process walk — a phase of work
  behind a dot.
- **All sixteen theme tokens now.** Rejected: the five unrendered state
  tokens would be colours no widget names, and LWSM-1031 lands them with
  the palettes that give them values. The nine base tokens are kept whole
  because they are an adopted set and splitting them is arbitrary.
- **Probe inline on the owning thread, deferring the worker to P05 or
  P06.** Tempting on the numbers: 33 ms once a second is a 3.3 % duty
  cycle, and the worker costs a task class, a queued signal and the
  in-flight guard.
  Rejected because `docs/design.md § State management` states the worker
  requirement with no phase condition, and because deferring it means
  `PortProbe`, `ProjectController` and the signal wiring are all built to a
  thread affinity that later has to change — three components rebuilt to
  save about twenty-five lines now.
- **`ss -tlnp` instead of `psutil`.** Already rejected in
  `docs/discovery.md § Tech stack` as fragile; recorded here only so it is
  not re-proposed.

## 9. Out of scope

- Distinguishing `running (foreign)` from `port blocked` — LWSM-1011.
  **The accepted consequence:** a row reads `running` when an unrelated
  process holds the port, so the word describes the *port*, not the
  project. P02 shows no holder identity and offers no action on it, so
  nothing is gated on the ambiguity; LWSM-1011 both splits the states and
  lands ADR-0004's holder disclosure.
- Re-pointing the row's state token from `state_running` to
  `state_foreign` / `state_blocked` once the seven states exist —
  LWSM-1011, with the remaining palettes from LWSM-1031 (§4.4).
- Making the poll interval settings-backed. `docs/design.md § Data flow`
  calls the 1-second poll "(default, settings-backed)"; P02 has no settings
  file, so `POLL_INTERVAL_MS` is a module constant and LWSM-1018's settings
  dialog is where it becomes a setting.
- `confirmed_port` and the framework-default rung of the effective-port
  chain — LWSM-1038, LWSM-1006.
- Scanning, the registry merge, and writing `projects.json` — LWSM-1006,
  LWSM-1007.
- Start / stop / restart and the optimistic overlay — LWSM-1009,
  LWSM-1010.
- The remaining themes, the text-size control and the T8 test surfaces —
  LWSM-1031, LWSM-1032.

## 10. Resource cost

No new dependency: `PySide6==6.11.1` and `psutil==7.2.2` are already
pinned in `pyproject.toml` and were unused. One `PortSnapshot` per tick,
holding a `frozenset[int]` of the machine's listening ports and discarded
on the next tick — no accumulation. (The count is not stated: two
measurements minutes apart on an idle machine gave 9 and 12, so it is a
property of the machine at an instant, not a figure this spec can assert.)
The controller holds one `dict[Path, ProjectStatus]` sized by the record
count, and the window holds one widget per record, created once. No new
build target. One `_SnapshotTask` per tick, deleted by the pool as `run()`
returns, and one `_SnapshotSignals` for the controller's whole life rather
than one per task; at most one task is outstanding (INV-12), so the ceiling
is one task, not one per tick elapsed.

That ceiling was **asserted here and not delivered** until LWSM-1098's
sibling fix. A per-task signaller had to outlive `run()` for its queued
emission to survive, which forced `setAutoDelete(False)` — and
`QThreadPool.start()` has already transferred ownership to C++, so clearing
the controller's own reference freed nothing. Measured: 200 live
`_SnapshotTask` objects after 200 completed polls, one per tick, ~2.5 KiB
each — about 210 MiB/day at the 1000 ms interval, plus a connection list
growing without bound behind each retained signaller. Moving the signaller
onto the controller is what lets `autoDelete` stay on.
`test_completed_tasks_do_not_accumulate` now holds the claim.

## 11. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_registry.py::test_unusable_files_are_refused` |
| INV-2 | `tests/test_registry.py::test_bad_record_skipped_others_load` |
| INV-3 | `tests/test_controller.py::test_one_snapshot_per_poll` |
| INV-3b | `tests/test_ports.py::test_one_net_connections_call_per_snapshot` |
| INV-4 | `tests/test_controller.py::test_status_is_rederived_not_remembered` |
| INV-4b | `tests/test_controller.py::test_probe_error_holds_previous_status` |
| INV-4c | `tests/test_controller.py::test_an_unexpected_exception_does_not_wedge_the_poll_loop` |
| INV-5 | `tests/test_controller.py::test_first_poll_emits_then_only_on_change` |
| INV-6 | `tests/test_mainwindow.py::test_state_is_a_word_not_only_colour` |
| INV-7 | `tests/test_mainwindow.py::test_row_follows_a_real_socket` |
| INV-8 | `tests/test_layering.py::test_core_never_imports_qtwidgets` |
| INV-8b | `tests/test_layering.py::test_no_colour_literals_in_widget_code` |
| INV-9 | `tests/test_ports.py::test_snapshot_follows_a_real_socket` |
| INV-10 | `tests/test_registry.py::test_port_ranges_differ_by_field` |
| INV-11 | `tests/test_controller.py::test_probe_runs_off_the_owning_thread` |
| INV-12 | `tests/test_controller.py::test_tick_skipped_while_probe_in_flight` |
| INV-13 | `tests/test_mainwindow.py::test_focus_survives_a_status_change` |
| INV-14 | `tests/test_main.py::test_version_needs_no_display` |
| INV-15 | `tests/test_mainwindow.py::test_registry_error_opens_an_empty_window` |
| INV-16 | `tests/test_controller.py::test_stop_waits_for_the_outstanding_task` |
| INV-17 | `tests/test_mainwindow.py::test_focus_is_visible_not_merely_held` |
| INV-18 | `tests/test_theme.py::test_every_text_token_clears_the_text_floor` |
| INV-19 | `tests/test_mainwindow.py::test_the_row_exposes_only_its_three_cells` |
| INV-20 | `tests/test_mainwindow.py::test_the_row_stays_grouped_when_the_window_is_wide` |
| INV-21 | `tests/test_registry.py::test_a_newline_in_a_name_cannot_forge_a_log_line`, plus `::test_no_file_sourced_value_is_interpolated_without_the_clip` for the mechanism-wide sweep |
| INV-22 | `tests/test_mainwindow.py::test_a_state_change_is_announced` |
| INV-23 | `tests/test_mainwindow.py::test_the_state_word_takes_its_colour_from_the_status` |
| INV-24 | `tests/test_mainwindow.py::test_the_theme_reaches_the_cells_not_only_the_window` |
| INV-25 | `tests/test_mainwindow.py::test_an_application_font_change_reflows_an_existing_row` |
| O8.2 — a row being keyboard-**reachable** at all | **nothing** — INV-13 focuses a row programmatically and asserts the focus survives a flip; nothing asserts the row is in the tab chain. LWSM-1032's keyboard-reachability row is the surface |
| O8.2 — tab order matching visual order | **nothing** — same surface, same item |
| O8.4 — reflow at 200 % text size | **partly** — `test_the_glyph_is_not_clipped_when_the_text_size_doubles` renders at 200 % and asserts the glyph's ink stays inside its column (LWSM-1101), and `test_the_row_resizes_its_cells_when_the_font_grows` covers the cell minimums. Neither covers the row *reflowing*; the text-size control itself is LWSM-1032. Both drive `row.setFont`, and until LWSM-1119 that was the **only** route that worked, so this row read "partly covered" while the application-font route was dead — INV-25 now covers that route, and it is the one a control uses |
| "The state word is first in the row" | **nothing** — §4.4 claims it and no invariant asserts it; LWSM-1032's x-position row is the surface |
| `§ O7`'s font-family and pixel-size half | **nothing**, and **unowned** — INV-8b checks colour literals only, so a widget pinning `setFont(QFont("DejaVu Sans"))` or a fixed height passes every test here. No roadmap item schedules this check; LWSM-1032's rows are about rendered output, not about source literals |
| The 2 s criterion under load | **nothing** — INV-7 measures one project on an idle machine; the ≤250 ms snapshot budget at 20 projects is unmeasured until there are 20 projects to measure, which no roadmap item yet creates |

**Five `nothing` rows**, plus one partly-covered. Three are surfaces
LWSM-1032 creates; **two are unowned** — the `§ O7` font/size check and the
2-second criterion under load — and being unowned is the point of listing
them, since a gap with a roadmap id is scheduled and a gap without one is
only known. Per `spec-format § 0`'s "one number that matters", five is this
spec's honest error budget, and the accessibility rows are still the bulk of
it — the expected shape for a phase that builds the row correctly but cannot
yet test that it did.

The count was **eight**, and stayed eight after INV-17 and INV-18 landed
(LWSM-1108). Two rows claimed "nothing" against checks that existed: focus-ring
contrast is `test_theme.py::test_the_focus_ring_clears_the_indicator_floor`,
and the three state tokens' contrast is
`test_every_text_token_clears_the_text_floor`, which parametrises over
`state_running`, `state_stopped` and `state_unknown`. § 7's table *was* updated
when they landed and this section was not — so the number was wrong by two, and
a count re-asserted rather than re-derived is how it stayed wrong. Recomputed
from the rows above, not carried forward.

## 12. Cross-doc impact

- `CHANGELOG.md` — an Added entry for the window and the status row.
- `CLAUDE.md § Module map` — five new modules and the core/UI split rule as
  it is actually enforced.
- `ROADMAP.md` — LWSM-1005 to ✅; LWSM-1059 annotated, since P02 is what
  first exercises `pytest-qt` and both markers.
- `docs/design.md` — **no change, and that is a checked claim rather than
  an assumption.** Three places where this spec first looked like it
  diverged were reconciled in its own favour, not the design's: the probe
  now runs on a worker (§4.3), the row's state word is `unknown` where the
  design says *unknown* (§4.3), and the two-state collapse is recorded as a
  subset with the accepted consequence named (§3, §9). Two real deltas
  remain, both scheduled rather than silent:
  - **A narrowing.** `state_running`'s provisional binding — §4.4 and §9
    carry it as a re-point LWSM-1011 performs.
  - **An addition.** `state_unknown` is an **eighth** token, outside the
    seven that `docs/design.md § Tokens, not colours` says ADR-0004
    "defines the set" of. It is P02-local: ADR-0004 lists states derived
    from observation and `UNKNOWN` is the absence of one, so it is not a
    candidate for that list. Whether design.md gains a sentence or
    LWSM-1031 absorbs the token when it lands the palettes is LWSM-1031's
    call; either way the token cannot quietly become a de-facto eighth
    derived state.
- `docs/standards/coding.md § O3` — its XDG paragraph says of the config
  half "no code yet and this is the rule it must follow when **P09** writes
  it". P02 writes it: `registry.py::default_projects_path`. The sentence
  becomes stale the moment this ships and should name P02.

## 13. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
| 1 | 2026-08-06 | 2 | 2 | 6 | 8 | 10 | 26 verified, 0 unverified, 26 fixed. Dimensions: dim 2×6, dim 5×6, dim 7×6, dim 15×4, dim 4×3, dim 6×2, dim 10×2, dim 1×1. Both CRITICALs were doc-vs-design conflicts: the probe ran on the UI thread against `design.md § State management`'s worker rule, and INV-4 forbade the very carry-over §6 required on a failed probe. Contract added: `ProjectStatus.UNKNOWN`, `RowView`, the worker + in-flight skip, in-place row updates. INV-3 and INV-8 split because each claimed more than its named test exercised. 391 → 684 lines. |
| 2 | 2026-08-06 | 2 | 1 | 8 | 12 | 12 | 25 verified (18 fix collateral from loop 1, 7 draft defects), 0 unverified, 25 fixed. Dimensions: dim 15×7, dim 5×6, dim 7×5, dim 4×4, dim 10×3, dim 2×2, dim 1×1, dim 6×1, dim 12×1. Two invariants could not fail for the breach they named: INV-4's fresh-controller fixture passes under a sticky implementation, and INV-11 named `psutil` and `MainWindow`, neither of which its fixture has. `QRunnable` cannot carry a `Signal` — `issubclass(QRunnable, QObject)` is `False`, verified — so the worker became `_SnapshotTask(QObject, QRunnable)`. Both lanes agreed the XDG citation was wrong and both named the wrong replacement (`§ O6`); verification found `§ O3`. `nothing` rows 4 → 6 once promises that only looked covered were separated. 684 → 833 lines. |
| 3 | 2026-08-06 | 1 | 0 | 3 | 5 | 5 | 13 verified, 0 unverified, 13 fixed. Almost all fix collateral from loops 1–2, which is why one lane rather than two. The lane named the check this run owed itself: loop 2 prescribed `_SnapshotTask(QObject, QRunnable)` **without executing it**. Executed here — both that shape *and* a plain `QRunnable` with a composed signaller work under 6.11.1, so the lane's premise (Shiboken forbids it) was wrong while its advice was right; the composed signaller is adopted as the documented idiom. Also caught: the accessible name would have included the `●` glyph and announced "black circle"; INV-15 named a test that could not observe it, since `main` blocks in `app.exec()` — `build_window` is the seam that fixes it. Added INV-16 (shutdown waits for the outstanding task). `nothing` rows 6 → 8, two of them unowned. 833 → 921 lines. **Converged by cap.** No verified finding is left unfixed. |
