# LWSM-1005 — Render one hand-written project as a live status row

**Status:** spec draft (2026-08-06).
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

## 3. Scope decisions (agreed with the user)

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
- **A third *label*, `unknown`, for a record with no port.** Author's call
  during this spec's review loop, not the user's, and it is a reading of
  "two states" rather than a departure from it: `running` and `stopped`
  remain the only two states *derived from observation*, and `unknown` is
  what a row shows when there is no port to observe — the same word
  `docs/design.md § The effective port` uses for the same condition.
  Calling such a row `stopped` would be the one thing `§ O5` forbids.
- **The probe goes on a worker in P02, not later.** `docs/design.md
  § State management` requires it unconditionally, and `§ O2` calls a
  worker-to-widget boundary the codebase's single most likely defect. P02
  is the cheapest place it will ever be built — one project, no process
  I/O. The alternative was deferring it as a P02 deviation, rejected in §8.
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
    path: Path                  # absolute, ADR-0005's identity
    name: str
    port: int | None            # declared; ADR-0005 "detected" half
    port_override: int | None   # user-owned half

    @property
    def effective_port(self) -> int | None: ...

class RegistryError(Exception): ...

def default_projects_path() -> Path:
    """$XDG_CONFIG_HOME/localwebservermanager/projects.json, falling back
    to ~/.config when the variable is unset or not absolute — the config
    half of `docs/standards/coding.md § O4`'s XDG rule."""

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
and no records are returned, for exactly four shapes — the file itself is
unusable and ADR-0005 forbids partially parsing it:

1. The file is absent.
2. The file is not valid JSON, or its top level is not an object.
3. `schema_version` is absent, or is anything but the integer `1`. Absent
   counts: a file that does not say which schema it is written to is one
   this build cannot claim to understand.
4. `projects` is absent, or is not a list.

Every field of every record is then type-checked before use:

| Field | Accepted | Why that range |
|---|---|---|
| `path` | non-empty string, absolute, unique within the file | ADR-0005 makes the absolute path the identity; a duplicate would give two rows one identity |
| `name` | non-empty string | it is the row's label and the accessible name |
| `port` | absent, `null`, or an integer 1–65535 | the *declared* half. A project that genuinely declares 80 or 443 is legitimate data, so ADR-0005's 1024–65535 floor does **not** apply here — that floor governs the override |
| `port_override` | absent, `null`, or an integer 1024–65535 | ADR-0005: "an override is validated at entry against the same 1024–65535 range ADR-0002 requires" |

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

class PortProbe:
    def snapshot(self) -> PortSnapshot: ...
```

`snapshot()` makes exactly one `psutil.net_connections(kind="tcp")` call
and keeps the `laddr.port` of every entry whose status is
`psutil.CONN_LISTEN`. One call per tick for the whole list, never one per
project — `docs/design.md § Data flow`. Port ownership (holder PID, exe,
cwd) is deliberately absent: P02 asks only *is anything listening*, and
adding the holder lookup would be implementing LWSM-1011 early.

`psutil.Error` from the call is caught and re-raised as `ProbeError`, so
the poll loop has one exception type to handle and a partial socket table
never reads as an empty one. `psutil.Error` is the whole surface —
`issubclass(psutil.AccessDenied, psutil.Error)` → `True`, verified against
the pinned 7.2.2 — so naming its subclasses separately would only suggest
they were disjoint.

The `laddr` guard is deliberate belt-and-braces: on this machine no
listening entry has a falsy `laddr` (0 of 12, measured), but the field is
typed as possibly empty and a probe that raised `AttributeError` mid-tick
would take the poll down.

### 4.3 The poll

`src/lwsm/controller.py`, core, `QtCore` only:

```python
POLL_INTERVAL_MS = 1000

class ProjectStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"

@dataclass(frozen=True)
class RowView:                           # everything one row renders
    path: Path
    name: str
    effective_port: int | None
    status: ProjectStatus

class ProjectController(QObject):
    projects_changed = Signal()          # docs/design.md § State management
    def __init__(self, records: list[ProjectRecord], probe: PortProbe,
                 parent: QObject | None = None) -> None: ...
    def start_polling(self) -> None: ...
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
it is what a record with no `effective_port` gets, because there is no port
to observe and calling that `stopped` would assert something nobody looked
at (`§ O5`). `docs/design.md § The effective port` uses the same word for
the same condition — "one with nothing at all is *unknown*".

**The probe runs off the UI thread.** `docs/design.md § State management`
is unconditional: "the socket-table probe runs on a worker so a slow
`psutil` call cannot freeze the window", and `§ O2` requires a worker to
reach the UI **only** through a queued signal. So `poll_once` does not
probe; it hands a `QRunnable` to `QThreadPool.globalInstance()`, and the
runnable emits its `PortSnapshot` back on a `Signal`, which the controller
receives on the UI thread (a cross-thread connection is queued by default)
and classifies there. Classification touches no OS state, so it is cheap
and belongs where the signal lands.

Getting this boundary right in P02 is the point of building it now: `§ O2`
calls a direct widget call from a worker "the single most likely defect in
this codebase", and P02 is the cheapest place it will ever be — one
project, no process I/O, nothing to unpick.

**A tick whose predecessor is still in flight is skipped, not queued** —
`docs/design.md § Data flow`, verbatim: "the poll skips a tick rather than
queueing". One `_in_flight` flag, cleared when the result arrives or the
runnable fails.

`start_polling()` calls `poll_once()` **immediately** and then starts the
`QTimer`, so the window is populated at once rather than blank for the
first second. The first result always emits `projects_changed`, because the
previous-status map is empty and therefore differs.

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

`src/lwsm/mainwindow.py` (UI layer) builds one row widget per `RowView`
**once**, and on each `projects_changed` **updates the existing widgets in
place** — the changed rows' text and tokens only. It does not rebuild the
list. Rebuilding would destroy and recreate every row widget on any one
project's flip, which discards keyboard focus (`docs/design.md
§ Accessibility`: "the app never steals focus") and re-announces every
*unchanged* row to a screen reader — undoing at the widget level exactly
what the signal-level suppression in §4.3 achieves. Rows are only created
or destroyed when the record list itself changes, which in P02 is never.

Each row is, in visual and tab order:

| Cell | Content |
|---|---|
| state | the glyph (`●` running / `○` stopped / `?` unknown) then the **word** `running` / `stopped` / `unknown`, coloured from the matching state token |
| name | the project's display name |
| port | the effective port as a decimal string, or the literal `no port` |

The state cell is first, which `docs/design.md § Accessibility` requires
("the state word is first in the row"). Each row is a focusable widget
whose accessible name is built **from the three rendered cell strings, in
their visual order** — `f"{state_text}, {name_text}, {port_text}"`, giving
`"running, project-a, 5005"` and `"unknown, project-b, no port"`. Building
it from the cells rather than from the model is what makes
`docs/design.md § Accessibility`'s "no separate accessibility-only string
to drift" literally true, and it is why no row can announce `port None`.

Nothing sets a colour literal, a font family or a pixel size: colours come
from tokens, sizes from the text metric (`§ O7`).

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
3. `QApplication` is constructed, then `load_projects`, `PortProbe`,
   `ProjectController` and `MainWindow`, then `controller.start_polling()`
   and `app.exec()`. `main` returns `app.exec()`'s value.
4. A `RegistryError` is not fatal: the window opens with no rows and the
   status bar names the file and the reason (§6). A missing
   `projects.json` must not stop the app from starting, for the same reason
   an unwritable log does not.

`QApplication` is constructed inside `main`, never at module import, so
importing `lwsm.__main__` in a test does not require a display.

## 5. Invariants

- **INV-1** — `load_projects` raises `RegistryError`, and returns no
  records, for each of the four unusable-file shapes in §4.1: absent,
  not-a-JSON-object, `schema_version` absent or not the integer `1`, and
  `projects` absent or not a list.
  *Test:* `tests/test_registry.py::test_unusable_files_are_refused`,
  parametrised over all four so a new shape cannot be added without a case.
  *Breaks when:* a file carrying `"schema_version": 2`, or none at all, is
  parsed for its `projects` key anyway.

- **INV-2** — A record whose `path` or `name` is absent, not a string, or
  the empty string is skipped with a reason; so is a record whose `path`
  duplicates one already loaded, or is not absolute. Every well-formed
  record in the same file still loads.
  *Test:* `tests/test_registry.py::test_bad_record_skipped_others_load`,
  with a case per rejection reason.
  *Breaks when:* `{"path": "", "name": "x"}` loads as a record, or two
  records sharing one `path` both load and then collapse into one row.

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
  derived from that snapshot alone: a freshly-constructed controller given
  the same records reports `RUNNING` for a bound port with no prior
  observation. The single sanctioned carry-over is the failed-probe hold in
  INV-4b.
  *Test:* `tests/test_controller.py::test_status_is_rederived_not_remembered`.
  *Breaks when:* a previous status is consulted on a *successful* tick
  rather than only as the change-detector — which is how `§ O5` gets
  breached quietly.

- **INV-4b** — On a tick whose probe raised `ProbeError`, every status
  keeps its previous value and `projects_changed` is not emitted.
  *Test:* `tests/test_controller.py::test_probe_error_holds_previous_status`.
  *Breaks when:* a failed probe is treated as an empty snapshot, which
  reports every project `stopped` on the strength of a `psutil` error — a
  state nobody observed, and the worse of the two failures because it looks
  like news.

- **INV-5** — `start_polling()` emits `projects_changed` on its immediate
  first poll; afterwards the signal is emitted on a tick whose statuses
  differ from the previous tick, and not on one whose statuses are
  identical.
  *Test:* `tests/test_controller.py::test_first_poll_emits_then_only_on_change`.
  *Breaks when:* the emit is unconditional — which makes the screen reader
  re-announce every row once a second — or when the first poll is left to
  the timer, which leaves the window blank for a second.

- **INV-6** — Every state the row shows is present as text. Removing all
  colour and all glyphs from a row still leaves `running`, `stopped` or
  `unknown` readable.
  *Test:* `tests/test_mainwindow.py::test_state_is_a_word_not_only_colour`,
  asserting the row's visible text contains the status word and that its
  accessible name does too.
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
  exist rather than one with a port we will not accept.

- **INV-11** — `psutil.net_connections` is never called on the thread that
  owns `MainWindow`.
  *Test:* `tests/test_controller.py::test_probe_runs_off_the_owning_thread`,
  recording `threading.get_ident()` inside a fake probe and asserting it
  differs from the test thread's.
  *Breaks when:* `poll_once` probes inline — a 33 ms UI stall every second
  today, and an unbounded one the first time `psutil` blocks, which is the
  freeze `docs/design.md § State management` puts the worker there to
  prevent.

- **INV-12** — A tick that fires while a probe is still in flight is
  skipped: two ticks with one slow probe outstanding produce one
  `snapshot()` call, not two.
  *Test:* `tests/test_controller.py::test_tick_skipped_while_probe_in_flight`.
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

- **INV-15** — A `RegistryError` does not stop the app: the window opens,
  shows no rows, and its status bar names the file and the reason.
  *Test:* `tests/test_mainwindow.py::test_registry_error_opens_an_empty_window`.
  *Breaks when:* the exception propagates out of `main` — a missing
  `projects.json` is first-run, not a crash, on the same reasoning that
  keeps an unwritable log from killing startup.

## 6. Failure modes

- **`projects.json` absent.** `RegistryError`; the window opens empty with
  a status-bar line naming the path it looked at (INV-15). First run is not
  an error state until LWSM-1008 lands the scan-and-confirm flow.
- **`projects.json` unparseable, not an object, or missing / wrong
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
- **The socket table cannot be read.** `ProbeError`, logged at WARNING;
  every row keeps its previous status and no signal is emitted (INV-4b).
  Reporting `stopped` on a failed probe would be reporting a state nobody
  observed (`§ O5`). This is the canonical statement of the behaviour; §4.3
  points here.
- **The probe outlives its tick.** The next tick is skipped rather than
  queued (INV-12). A probe that never returns stops the status updating and
  leaves the last-known state on screen — visibly stale, rather than
  wrongly confident. No watchdog: nothing here may time out into a wrong
  state (ADR-0004 § Slowness is not failure).
- **Two records share a port.** Both rows read `running` off the same
  socket. ADR-0005 catches this at merge time, and there is no merge in
  P02 — LWSM-1007 owns it. Named here so a reviewer knows it was seen.
- **A server binds only IPv6, or only a non-loopback address.** The
  snapshot keys on port alone, so it is seen. This is deliberately looser
  than "the project is reachable at `localhost:<port>`"; the health check
  that closes that gap is LWSM-1034.

## 7. Tests

New files, all headless (`§ T6`; `scripts/local-ci.sh` already exports
`QT_QPA_PLATFORM=offscreen`, and a new `tests/conftest.py` sets it when
unset so a bare `pytest` cannot open a real window):

| File | Marker | Locks |
|---|---|---|
| `tests/test_registry.py` | — | INV-1, INV-2, INV-10 |
| `tests/test_ports.py` | `integration` | INV-9, INV-3b |
| `tests/test_controller.py` | — | INV-3, INV-4, INV-4b, INV-5, INV-11, INV-12 |
| `tests/test_mainwindow.py` | `gui`, `integration` | INV-6, INV-7, INV-13, INV-15 |
| `tests/test_layering.py` | — | INV-8, INV-8b |
| `tests/test_main.py` (existing) | — | INV-14 |

Ports come from binding `0` and asking the socket, never a literal
(`§ T3`). Waits are `qtbot.waitUntil` on the condition, never a sleep
(`§ T4`). Every fixture closes its socket in teardown (`§ T5`), and no test
reads the real `~/.config/localwebservermanager/` (`§ T1`).

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
- **Probe inline on the UI thread, deferring the worker to P05 or P06.**
  Tempting on the numbers: 33 ms once a second is a 3.3 % duty cycle, and
  the worker costs a `QRunnable`, a queued signal and the in-flight guard.
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
build target. One `QRunnable` per tick, owned by `QThreadPool` and released
when it completes; at most one is outstanding (INV-12).

## 11. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_registry.py::test_unusable_files_are_refused` |
| INV-2 | `tests/test_registry.py::test_bad_record_skipped_others_load` |
| INV-3 | `tests/test_controller.py::test_one_snapshot_per_poll` |
| INV-3b | `tests/test_ports.py::test_one_net_connections_call_per_snapshot` |
| INV-4 | `tests/test_controller.py::test_status_is_rederived_not_remembered` |
| INV-4b | `tests/test_controller.py::test_probe_error_holds_previous_status` |
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
| O8.2 — focus **ring** contrast (reachability is INV-13's neighbour, the ring is not) | **nothing** — no surface asserts ring contrast until LWSM-1032 lands the T8 rows |
| O8.4 — reflow at 200 % text size | **nothing** — the text-size control itself is LWSM-1032; P02 pins no sizes, which is necessary and not sufficient |
| The 2 s criterion under load | **nothing** — INV-7 measures one project on an idle machine; the ≤250 ms snapshot budget at 20 projects is unmeasured until there are 20 projects to measure, which no roadmap item yet creates |
| The row's tab order matching visual order | **nothing** — INV-13 asserts focus *survives*, not that the order is right; LWSM-1032's keyboard-reachability row is the surface |

Four `nothing` rows. Three are surfaces LWSM-1032 creates; one waits on a
project count P02 does not have and nothing yet schedules.

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
  subset with the accepted consequence named (§3, §9). The one genuine
  narrowing is `state_running`'s provisional binding, which §4.4 and §9
  carry as a scheduled re-point rather than as a contradiction.

## 13. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
| 1 | 2026-08-06 | 2 | 2 | 6 | 8 | 10 | 26 verified, 0 unverified, 26 fixed. Dimensions: dim 2×6, dim 5×6, dim 7×6, dim 15×4, dim 4×3, dim 6×2, dim 10×2, dim 1×1. Both CRITICALs were doc-vs-design conflicts: the probe ran on the UI thread against `design.md § State management`'s worker rule, and INV-4 forbade the very carry-over §6 required on a failed probe. Contract added: `ProjectStatus.UNKNOWN`, `RowView`, the worker + in-flight skip, in-place row updates. INV-3 and INV-8 split because each claimed more than its named test exercised. 391 → 684 lines. |
