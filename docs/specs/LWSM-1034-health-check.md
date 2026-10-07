<!-- ants-spec-format: 1 -->
# LWSM-1034 — Ask a running site whether it works, and show the answer on its row

**Status:** spec draft (2026-10-07).
**Kind:** implement.
**Source:** ROADMAP LWSM-1034 (user-2026-08-03).
**Blocked by:** LWSM-1011 (shipped 2026-10-02).

**Layman:** For a project you choose, the app asks the site for a page every
ten seconds and shows the answer under its port, so a site that is running but
broken stops looking fine.

## 1. Goal

After this ships, a project can be marked from its row's right-click menu to
have its site checked. While that project reads `running`, the app sends an
HTTP `GET` for one page of it every ten seconds and shows the answer as words
on the last line of the port cell: `HTTP 200`, `HTTP 500`, `no response`. The
choice and the page are saved in `projects.json`. The answer is not saved and
never changes the row's state, colour or glyph.

## 2. Problem

1. **A port probe cannot see a broken server.** `ProjectController._classify`
   derives every state from one `ports.PortSnapshot`, which records only which
   ports are listening and who holds them. A server that binds and then fails
   every request reads `running`, exactly like a healthy one.
2. **Nothing in the app makes a request.** No module in `src/` imports
   `http.client` or `urllib`; Open hands `mainwindow.project_url` to the
   desktop and reads nothing back.
3. **A request is someone else's code running.** The `GET` is handled by the
   project's own server, so it must be opt-in per project, sent only to that
   project's own port on `localhost`, and to a page the user chose.

## 3. Scope decisions (agreed with the user)

From the user, 2026-10-07 (notes on LWSM-1034):

- **Turned on from the row's right-click menu**, with a second item to change
  the page it asks for. The app has no per-project settings screen.
- **The answer is a new last line of the port cell.** The user first chose a
  second line under the state word; measured in the suite's font (DejaVu Sans
  9), that widens the state column from its 54 px floor to 73 px for
  `no response`, which pushes the widest row past the 600 px lens. The port
  cell's widest existing line, `(sources differ)`, is 91 px, so a line there
  widens no row. The user chose this instead.
- **Every ten seconds, fixed.** No new setting.
- **Words only.** A bad answer changes no state, colour or glyph, so
  ADR-0004's table is unchanged.

Decided by the author, recorded so they are not re-argued:

- **Only a row reading `running` is asked.** `running (wrong port)` means the
  server is not on the port asked about, and `running (foreign)` is a server
  this app cannot vouch for, which is why LWSM-1141 keeps Open off those rows.
- **A redirect is an answer, not an instruction.** `HTTP 302` is shown and not
  followed, so the request can never leave `localhost:<port>`.
- **An imported profile cannot turn checking on or change the page.** Both
  fields join `registry.NEVER_IMPORTED_FIELDS`, for the reason that set exists:
  a profile is a file from somewhere else, and these two decide what request
  this app sends to a server.
- **The answer is kept in memory only.** It describes the server as it was a
  few seconds ago; saving it would show a stale answer after a restart.

## 4. Design

### 4.1 Asking: `src/lwsm/health.py`

A new core module importing no Qt at all, like `ports.py`.

```python
HEALTH_TIMEOUT_SECONDS = 2.0

def ask(port: int, path: str, *, timeout: float = HEALTH_TIMEOUT_SECONDS) -> int | None:
    """GET `path` from localhost:`port`. The status code, or None for no answer."""
```

It uses `http.client.HTTPConnection("localhost", port, timeout=timeout)`,
sends `GET <path>` with `User-Agent: LocalWebServerManager/<__version__>
health check` and `Connection: close`, reads the status line and closes without
reading the body. `http.client` follows no redirect. It returns `None` on
`OSError` (refused, reset, timeout) and on `http.client.HTTPException` (a reply
that is not HTTP). Any other exception propagates to the caller.

The connection host is the literal `"localhost"` and `path` is only the
request target, so `path` cannot change where the request goes. `path` is
validated before it reaches here (§ 4.3).

### 4.2 Scheduling: `controller.py`

```python
HEALTH_INTERVAL_MS = 10_000
HEALTH_THREADS = 4

@dataclass(frozen=True)
class HealthAnswer:
    code: int | None  # None: no HTTP answer within the timeout
```

`ProjectController` gains:

- `_health_timer`, a `QTimer` at `HEALTH_INTERVAL_MS`, started by
  `start_polling` and stopped by `stop`. Its tick is `check_health_once`.
- `_health_pool`, its own `QThreadPool` capped at `HEALTH_THREADS`, never the
  snapshot pool (capped at one so polls cannot overlap) or the service pool.
- `_health_in_flight: set[Path]` and `_health: dict[Path, tuple[int, str,
  HealthAnswer]]`, the answer keyed by the port and page it was asked for.

`check_health_once` starts one task per record where all hold: `health_check`
is set; the **derived** status in `_statuses` is `RUNNING` (not the optimistic
overlay); `effective_port` is not `None`; and the path is not in
`_health_in_flight`. A project still waiting on its last answer is skipped,
not queued, as `poll_once` skips.

The task runs `health.ask(port, record.health_path or "/")` and emits `(path,
port, page, code)`. `run()` lets nothing escape, on `_SnapshotTask`'s two-layer
pattern: an exception from `ask` is logged at warning and emitted as "no answer
to show", which removes any stored answer and clears the in-flight mark.

The slot, on the owning thread, returns at once after `stop()`. Otherwise it
clears the in-flight mark and stores the answer **only if** the record still
has `health_check` set, still reads `RUNNING`, and still has that port and that
page. It then emits `projects_changed` only if the stored answer changed.

A stored answer is removed when a poll's classification moves the project out
of `RUNNING`, when `set_records` replaces a record whose `health_check` is off
or whose effective port or page differs, and when the record leaves the list.

`stop()` gives `_health_pool` the bounded wait and `abandon_pool` treatment it
gives `_service_pool`.

`RowView` gains:

```python
health_check: bool = False
health_path: str = "/"
health: HealthAnswer | None = None  # None: nothing to show
```

`rows` fills `health` only when the stored answer's port and page match the
record's current ones.

### 4.3 The file format

Two optional keys per project object, written after `browser`:

```json
{
  "path": "/srv/project-a",
  "name": "Project A",
  "browser": null,
  "health_check": true,
  "health_path": "/health"
}
```

`schema_version` stays `1` under LWSM-1007 § 4.2's compatibility rule: both
keys are optional and a file without them loads as before. An older build keeps
them through `ProjectRecord.unknown` (LWSM-1218).

`ProjectRecord` gains `health_check: bool = False` and `health_path: str | None
= None`, where `None` means `/`. Both are in `USER_FIELDS`, so a rescan keeps
them, and both are in `NEVER_IMPORTED_FIELDS`, with `_NEVER_IMPORTED_WORDS`
entries `"health check setting was"` and `"health check page was"`.

```python
MAX_HEALTH_PATH_CHARS = 512
HEALTH_PATH_PATTERN = re.compile(r"\A/[A-Za-z0-9\-._~!$&'()*+,;=:@/%?]*\Z")

def health_path_ok(value: str) -> bool:
    """The one test the loader and the menu both apply."""
```

| Key | Type | Default when absent | Refused when |
|---|---|---|---|
| `health_check` | `true` / `false` | `false` | not a JSON boolean (`_bool_or_reason`) |
| `health_path` | string or `null` | `null` | not a string; longer than `MAX_HEALTH_PATH_CHARS`; or not matched by `HEALTH_PATH_PATTERN` |

A refusal follows LWSM-1007 § 4.2's blanket rule: the field takes its default
and one reason is reported. Both are user fields, so a refusal adds to
`LoadResult.user_fields_refused`, which is the existing rule for every user
field. The pattern's character set is RFC 3986's path-and-query characters, so
a space, a control character, a `#` and every non-ASCII character are refused.

### 4.4 The row

`mainwindow.ProjectRow` gains two actions on its `ActionsContextMenu`, after
the existing two:

- `health_action`, checkable: `Check that the site &answers`, checked from
  `RowView.health_check`. Triggering it calls
  `MainWindow.set_project_health_check(path, on)`.
- `health_page_action`: `Change the page it &checks…`. Triggering it calls
  `MainWindow.change_health_page(path)`, which asks through
  `MainWindow._ask_health_page(name, current) -> str | None` (a
  `QInputDialog.getText`, and the seam tests replace). `None` (cancelled)
  changes nothing. An empty answer stores `None`. An answer `health_path_ok`
  refuses is not saved, and `MainWindow.set_status_message` says
  `A page starts with / and has no spaces`.

Both setters follow `set_project_browser`: `replace` the record, then
`_write_records` with a translated status message naming the project.

**The port cell.** When `RowView.health` is set, `port_cell_text`'s output
gains a last line: `HTTP %1` with the code substituted by `str.replace` as
`port_text` does, or `no response` when `code` is `None`. Both are translated.
The cell's accessible name joins the confidence line with a space, as today,
and the health line with `, `: `port 5005 (confirmed), HTTP 500`.

**The detail.** `port_detail` gains one last sentence when `health` is set:
`The site answered HTTP %1 to %2.` or `The site did not answer %2 within 2
seconds.`, `%2` being the page through `configfile.display_text`.

## 5. Invariants

- **INV-1** — `health.ask` returns the status code a real local server sends,
  does not follow a redirect, and returns `None` for a refused connection, a
  timeout and a reply that is not HTTP.
  *Test:* `tests/test_health.py`, against an `http.server` thread on port 0
  answering 200, 500 and 302 to a different port, a closed port, a socket that
  accepts and never replies (with a 0.2 s timeout), and one that replies
  `hello\r\n`.
  *Breaks when:* `urllib.request.urlopen` is used, which follows the 302 and
  raises on the 500; or an `except` names only `ConnectionRefusedError`, so a
  timeout escapes.

- **INV-2** — The request goes to `localhost:<port>` whatever `path` holds.
  *Test:* `tests/test_health.py`, `ask(port, "@example.invalid/")` against the
  local server records one request whose target is `@example.invalid/`.
  *Breaks when:* the URL is built as `f"http://localhost:{port}{path}"` and
  parsed, which turns that path into a request to `example.invalid`.

- **INV-3** — Each refusal in § 4.3's table drops that field to its default,
  adds exactly one reason, and names the field in `user_fields_refused`; a
  file without either key loads with `health_check is False` and `health_path
  is None`.
  *Test:* `tests/test_registry.py`, parametrised over `"yes"`, `1`, `"health"`
  (no leading slash), `"/a b"`, `"/a#b"`, `"/é"`, `"/a\n"` and a 513-character
  path, plus the absent case.
  *Breaks when:* `health_path` is checked only for type, which lets `"health"`
  and a newline through to the request line.

- **INV-4** — A record with both fields set round-trips through
  `save_projects` and `load_projects`, a rescan keeps them, and
  `merge_imported` keeps the current record's values and reports each one the
  profile carried.
  *Test:* `tests/test_registry.py::test_write_then_load_round_trips` extended,
  plus one merge case and one import case.
  *Breaks when:* the fields are classified `DETECTED` (a rescan clears them),
  or left out of `NEVER_IMPORTED_FIELDS` (a profile turns checking on).

- **INV-5** — `check_health_once` asks only for a record with `health_check`
  set whose derived status is `RUNNING`, and never twice at once for one
  project.
  *Test:* `tests/test_controller.py`, a fake `ask` counting calls, over records
  in each derived state with the check on and off, a `RUNNING` record under a
  `STOPPING` overlay, and two ticks with one blocked call outstanding.
  *Breaks when:* the test reads `_status_of`, which returns the overlay; or the
  in-flight mark is cleared on start instead of on the answer.

- **INV-6** — An answer is shown only for the port and page it was asked for,
  and only while the project reads `RUNNING`.
  *Test:* `tests/test_controller.py`, three cases: the answer arrives after the
  page changed, after the port changed, and after a poll moved the project to
  `stopped`; `rows()` carries `health is None` in each.
  *Breaks when:* the slot stores the answer keyed by path alone.

- **INV-7** — No answer is delivered after `stop()` returns, and `stop()` stays
  within `STOP_WAIT_MS` with a health call that never returns.
  *Test:* `tests/test_controller.py`, LWSM-1005 INV-16's two shapes applied to
  the health pool: a completed call before `stop()`, and a blocked one.
  *Breaks when:* `stop()` waits on the snapshot and service pools only.

- **INV-8** — An exception other than those INV-1 names leaves that project
  checkable on the next tick.
  *Test:* `tests/test_controller.py`, a fake `ask` that raises `RuntimeError`
  once and then returns 200; the second tick stores `HealthAnswer(200)`.
  *Breaks when:* the exception escapes `run()`, which PySide6 swallows, so the
  in-flight mark is never cleared.

- **INV-9** — The port cell's last line is `HTTP <code>` or `no response`
  exactly when `RowView.health` is set, and its accessible name ends `, HTTP
  <code>` or `, no response`.
  *Test:* `tests/test_mainwindow.py`, three cases (`None`, `HealthAnswer(500)`,
  `HealthAnswer(None)`), asserting `row._port.text()` and its accessible name.
  *Breaks when:* the line is added to the state cell, or the accessible name
  keeps the raw newline.

- **INV-10** — A row with the widest port wording, the long name, the browser
  picker and a `no response` line still ends inside the 600 px band.
  *Test:* `tests/test_mainwindow.py`, a copy of
  `test_the_widest_port_wording_still_fits_one_lens_view` with
  `health=HealthAnswer(None)`.
  *Breaks when:* the health line goes under the state word, which measured
  73 px against the state column's 54 px floor.

- **INV-11** — The two menu items save the field and nothing else, and a page
  `health_path_ok` refuses is not saved.
  *Test:* `tests/test_mainwindow.py`, triggering `health_action` and
  `health_page_action` with `_ask_health_page` replaced, for `"/health"`, `""`,
  `None` and `"health"`, asserting the saved record each time.
  *Breaks when:* the menu path skips `health_path_ok`, which lets the UI store
  what the loader would refuse, so the next start makes the session read-only.

- **INV-12** — A page holding a control character or markup reaches the
  tooltip and the accessible description as plain text with the control
  character replaced. This is the trust boundary: `projects.json` is
  hand-editable.
  *Test:* `tests/test_mainwindow.py`, a `RowView` with `health_path`
  `"/<b>x</b>\u0007"` and `health=HealthAnswer(None)`.
  *Breaks when:* `port_detail` puts `health_path` in without `display_text`.

- **INV-13** — `health.py` imports no Qt.
  *Test:* `tests/test_layering.py`, `health` added to `CORE_MODULES`.
  *Breaks when:* the module grows a `QObject` to emit from.

## 6. Failure modes

- **The server is slow.** `ask`'s timeout applies to each socket operation,
  not to the whole call, so a server that sends its status line a byte at a
  time can hold one call for longer. The row reads `no response` once a call
  times out. Only that project's check waits: the in-flight mark skips it, the
  other threads keep serving, and `stop()` abandons a call that outlives
  `STOP_WAIT_MS`.
- **More than `HEALTH_THREADS` projects are checked.** The pool queues the rest
  for that tick. The in-flight mark stops a project being asked twice.
- **A check is turned on.** The first answer appears at the next tick, within
  ten seconds plus the timeout. Until then the cell shows no health line.
- **The page has side effects.** The user chose it; the app sends one `GET`
  every ten seconds and nothing else.
- **An older build edits the file.** It keeps both keys as unknown and writes
  them back. It does not ask.
- **A hand edit breaks a key.** § 4.3's refusals apply. The session goes
  read-only for user fields, as for any other user field.

## 7. Tests

The cases are named with each invariant in § 5:

- `tests/test_health.py` (new) — INV-1, INV-2.
- `tests/test_registry.py` — INV-3, INV-4.
- `tests/test_controller.py` — INV-5, INV-6, INV-7, INV-8.
- `tests/test_mainwindow.py` — INV-9, INV-10, INV-11, INV-12.
- `tests/test_layering.py` — INV-13.

Each new test is seen to fail by breaking its rule once in a scratch copy, per
`docs/standards/testing-overrides.md` § T9. INV-1 and INV-2 run a real server
on port 0 on a thread, per `testing-overrides.md` § T3.

## 8. Alternatives considered (and rejected)

- **The answer under the state word.** The user's first choice; rejected after
  measuring that it pushes the widest row past the 600 px lens (§ 3).
- **A new state and colour for a bad answer.** Rejected by the user: it
  changes ADR-0004's table and the classifier for something words can say.
- **A setting for the interval.** Rejected by the user; ten seconds is fixed.
- **`urllib.request`.** It follows redirects, so a redirect could send the
  request off `localhost`, and it raises on a 4xx or 5xx, which is an answer
  this feature reports.
- **Asking on every one-second poll.** Ten times the requests to someone
  else's server, and a slow server would hold the poll's single thread.
- **Saving the last answer.** It would show a server's old answer after a
  restart (§ 3).
- **Asking `running (foreign)` and `running (wrong port)` rows.** Rejected
  (§ 3).

## 9. Out of scope

- A per-project settings screen — deferred; not yet queued.
- An HTTPS check, or a check on another host — deferred; not yet queued.
- Telling an answer that is a redirect to a login page from a working site —
  deferred; not yet queued.

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1, INV-2 | `tests/test_health.py` |
| INV-3, INV-4 | `tests/test_registry.py`, the refusal, round-trip, merge and import cases |
| INV-5 to INV-8 | `tests/test_controller.py`, the cases named in § 5 |
| INV-9 to INV-12 | `tests/test_mainwindow.py`, the cases named in § 5 |
| INV-13 | `tests/test_layering.py` |
| § 4.3 both fields are USER | LWSM-1007's `test_every_record_field_is_classified` checks each field is in one set; INV-4's rescan case checks it is the user one |
| § 4.2 the ten-second interval | **nothing** — a constant, read by review |
| § 4.4 the wording | **nothing** — copy, reviewed by reading |

## 11. Cross-doc impact

- `docs/specs/LWSM-1007-registry-persistence.md` § 4.2: the key list points
  here for `health_check` and `health_path`.
- `docs/claude/module-map.md`: a `health.py` entry, and the two fields under
  the registry entry.
- `CHANGELOG.md`: one *Added* entry.

## 12. Cold-eyes loop log

Rows live in `../reviews/LWSM-1034-health-check-loop-log.md`.
