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
a colour — whether anything is listening on that project's port. The label
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
`docs/design.md § Architecture` names ten components of which zero exist.

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
    path: Path
    name: str
    port: int | None            # declared; ADR-0005 "detected" half
    port_override: int | None   # user-owned half

    @property
    def effective_port(self) -> int | None: ...

class RegistryError(Exception): ...

def load_projects(path: Path) -> tuple[list[ProjectRecord], list[str]]:
    """Returns (records, rejection messages). Raises RegistryError only
    when the file itself is unusable — absent, unparseable, or a
    schema_version this build does not know."""
```

`effective_port` is `port_override` if set, else `port`. That is the top
and third rungs of `docs/design.md § The effective port`; `confirmed_port`
(rung 2) arrives with LWSM-1038 and the framework default (rung 4) with
LWSM-1006, and until then a record with neither field reads `None`.

**The file is hand-editable, therefore attacker-editable** — ADR-0007's
reasoning about `settings.json`, applied here. Every field is type-checked
before use: `path` and `name` must be non-empty strings, `port` and
`port_override` must be integers in 1024–65535 (ADR-0005's entry
validation). A record failing any check is skipped and its reason returned
in the second tuple element; the surviving records still load, because one
typo must not blank the list. A bad `schema_version` is different and
raises: ADR-0005 forbids partially parsing an unknown version.

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

`psutil.AccessDenied` and `psutil.Error` from the call are caught and
re-raised as `ProbeError`, so the poll loop has one exception type to
handle and a partial socket table never reads as an empty one.

### 4.3 The poll

`src/lwsm/controller.py`, core, `QtCore` only:

```python
POLL_INTERVAL_MS = 1000

class ProjectStatus(StrEnum):
    RUNNING = "running"
    STOPPED = "stopped"

class ProjectController(QObject):
    projects_changed = Signal()          # docs/design.md § State management
    def __init__(self, records, probe, parent=None): ...
    def start_polling(self) -> None: ...
    def poll_once(self) -> None: ...
    def statuses(self) -> dict[Path, ProjectStatus]: ...
```

A `QTimer` at `POLL_INTERVAL_MS` calls `poll_once`, which takes one
snapshot, classifies every record against it, and emits
`projects_changed` **only when at least one status differs from the last
tick**. Suppressing the no-change emission is what
`docs/design.md § Accessibility` requires of a state change announcing
itself once rather than on every poll; it is also why the interval can stay
at 1 s without the screen reader chattering.

A record whose `effective_port` is `None` classifies as `STOPPED` — there
is nothing to observe, and inventing a state would breach `§ O5`. A
`ProbeError` logs at WARNING and leaves the previous statuses in place: an
unreadable socket table is not evidence that anything stopped.

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
`accent_soft`, `attention`, `border` — plus `is_dark`, plus the two state
tokens P02 renders: `state_running` and `state_stopped`. The other five
state tokens arrive with LWSM-1031 alongside the palettes that need them.
One default palette; `Theme` expands to a `QPalette` and a generated style
sheet.

`src/lwsm/mainwindow.py` (UI layer) builds one row per record in a
`QVBoxLayout` of row widgets, rebuilt from `statuses()` on every
`projects_changed`. Each row is, in visual and tab order:

| Cell | Content |
|---|---|
| state | the glyph (`●` running / `○` stopped) then the **word**, coloured from `state_running` / `state_stopped` |
| name | the project's display name |
| port | the effective port, or `no port` |

The state cell is first, which `docs/design.md § Accessibility` requires
("the state word is first in the row"). Each row is a focusable widget with
`setAccessibleName(f"{name}, {status}, port {port}")` — the same text the
row displays, so there is no accessibility-only string to drift. Nothing
sets a colour literal, a font family or a pixel size: colours come from
tokens, sizes from the text metric (`§ O7`).

## 5. Invariants

- **INV-1** — `load_projects` raises `RegistryError` naming the file and
  the version when `schema_version` is anything but `1`, and returns no
  records.
  *Test:* `tests/test_registry.py::test_unknown_schema_version_is_refused`.
  *Breaks when:* a file carrying `"schema_version": 2` is parsed for its
  `projects` key anyway.

- **INV-2** — A record with a non-string `path` or `name`, or a `port` /
  `port_override` outside 1024–65535, is skipped with a reason, and every
  well-formed record in the same file still loads.
  *Test:* `tests/test_registry.py::test_bad_record_skipped_others_load`.
  *Breaks when:* `{"path": 5, "name": "x", "port": 80}` either loads as a
  record or aborts the whole file.

- **INV-3** — One `poll_once` performs exactly one
  `psutil.net_connections` call regardless of how many records are
  classified.
  *Test:* `tests/test_controller.py::test_one_probe_call_per_poll`, a
  counting fake probe over 10 records.
  *Breaks when:* classification moves inside the per-record loop — the
  shape that turns a 33 ms tick into a 330 ms one at ten projects.

- **INV-4** — A project's status is derived from the current snapshot
  alone and never carried across a poll: a controller rebuilt from the same
  records reports `RUNNING` for a bound port with no prior observation.
  *Test:* `tests/test_controller.py::test_status_is_rederived_not_remembered`.
  *Breaks when:* a `_last_status` value is used as a fallback rather than
  only as the change-detector, which is how `§ O5` gets breached quietly.

- **INV-5** — `projects_changed` is emitted on a tick whose statuses differ
  from the previous tick, and not on a tick whose statuses are identical.
  *Test:* `tests/test_controller.py::test_no_signal_without_change`.
  *Breaks when:* the emit is unconditional — which makes the screen reader
  re-announce every row once a second.

- **INV-6** — Every state the row shows is present as text. Removing all
  colour and all glyphs from a row still leaves `running` or `stopped`
  readable.
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
  `QtWidgets`, and no widget module contains a colour literal.
  *Test:* `tests/test_layering.py::test_core_never_imports_qtwidgets` and
  `::test_no_colour_literals_in_widget_code`.
  *Breaks when:* a `QMessageBox` is reached for inside the controller —
  the first thing that makes the core need a display.

- **INV-9** — A `PortSnapshot` contains a port at the moment a real socket
  is listening on it, and does not contain that port once the socket is
  closed.
  *Test:* `tests/test_ports.py::test_snapshot_follows_a_real_socket`, over
  a socket bound to port `0`.
  *Breaks when:* the status filter is dropped, so every *connected* socket's
  local port reads as listening too — which would make an outbound
  connection from an ephemeral port look like a running server.

## 6. Failure modes

- **`projects.json` absent.** `RegistryError`; the window opens empty with
  a status-bar line naming the path it looked at. First run is not an error
  state until LWSM-1008 lands the scan-and-confirm flow.
- **`projects.json` unparseable JSON.** `RegistryError` naming the file and
  the decoder's message. Nothing is written back — P02 never writes the
  file at all.
- **A record is rejected.** Its reason reaches the status bar and the app
  log; the other rows render. Silent skipping would make a typo look like a
  deleted project.
- **The socket table cannot be read.** `ProbeError`, logged at WARNING;
  every row keeps its previous status. Reporting `stopped` on a failed
  probe would be reporting a state nobody observed (`§ O5`).
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
| `tests/test_registry.py` | — | INV-1, INV-2 |
| `tests/test_ports.py` | `integration` | INV-9 |
| `tests/test_controller.py` | — | INV-3, INV-4, INV-5 |
| `tests/test_mainwindow.py` | `gui`, `integration` | INV-6, INV-7 |
| `tests/test_layering.py` | — | INV-8 |

Ports come from binding `0` and asking the socket, never a literal
(`§ T3`). Waits are `qtbot.waitUntil` on the condition, never a sleep
(`§ T4`). Every fixture closes its socket in teardown (`§ T5`), and no test
reads the real `~/.config/localwebservermanager/` (`§ T1`).

Each test is seen to fail before its implementation lands — the registry
and controller tests against absent modules, the widget tests against a
window that renders no rows.

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
- **`ss -tlnp` instead of `psutil`.** Already rejected in
  `docs/discovery.md § Tech stack` as fragile; recorded here only so it is
  not re-proposed.

## 9. Out of scope

- Distinguishing `running (foreign)` from `port blocked` — LWSM-1011.
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
holding a `frozenset[int]` of listening ports (9 on this machine, measured
above) and discarded on the next tick — no accumulation. The controller
holds one `dict[Path, ProjectStatus]` sized by the record count, and the
window holds one widget per record. No new build target.

## 11. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_registry.py::test_unknown_schema_version_is_refused` |
| INV-2 | `tests/test_registry.py::test_bad_record_skipped_others_load` |
| INV-3 | `tests/test_controller.py::test_one_probe_call_per_poll` |
| INV-4 | `tests/test_controller.py::test_status_is_rederived_not_remembered` |
| INV-5 | `tests/test_controller.py::test_no_signal_without_change` |
| INV-6 | `tests/test_mainwindow.py::test_state_is_a_word_not_only_colour` |
| INV-7 | `tests/test_mainwindow.py::test_row_follows_a_real_socket` |
| INV-8 | `tests/test_layering.py::test_core_never_imports_qtwidgets`, `::test_no_colour_literals_in_widget_code` |
| INV-9 | `tests/test_ports.py::test_snapshot_follows_a_real_socket` |
| O8.2 — keyboard reachability and focus ring | **nothing** — no surface asserts tab order or ring contrast until LWSM-1032 lands the T8 rows; the row is built focusable and in visual order, and that is unverified |
| O8.4 — reflow at 200 % text size | **nothing** — the text-size control itself is LWSM-1032; P02 pins no sizes, which is necessary and not sufficient |
| The 2 s criterion under load | **nothing** — INV-7 measures one project on an idle machine; the ≤250 ms snapshot budget at 20 projects is unmeasured until there are 20, tracked by LWSM-1011 |

Three `nothing` rows. Two are surfaces LWSM-1032 creates; one waits on a
project count P02 does not have.

## 12. Cross-doc impact

- `CHANGELOG.md` — an Added entry for the window and the status row.
- `CLAUDE.md § Module map` — five new modules and the core/UI split rule as
  it is actually enforced.
- `ROADMAP.md` — LWSM-1005 to ✅; LWSM-1059 annotated, since P02 is what
  first exercises `pytest-qt` and both markers.
- `docs/design.md` — no change. This spec implements a subset and says so;
  nothing here contradicts it.

## 13. Cold-eyes loop log

| Loop | Date | Lanes | CRIT | HIGH | MED | LOW | Outcome |
|------|------|-------|------|------|-----|-----|---------|
