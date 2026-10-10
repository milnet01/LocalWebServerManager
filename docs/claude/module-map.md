# Module map

Moved word for word out of `CLAUDE.md` on 2026-10-01, to keep the
always-loaded instructions under Claude Code's size limit.
`CLAUDE.md` § Module map points here and still holds the rules.

The modules below are the list; P03 and P05 each add to it, so no
count is written here (`documentation-overrides.md § DOC1`).

- **`src/lwsm/__init__.py`** — the package docstring stating that
  rule, and `__version__`.
- **`src/lwsm/__main__.py`** — `main()`, plus the thin **`run()`**
  the `lwsm` console script and `python -m lwsm` actually name.
  `run()` is `main()` followed by
  `exit_without_waiting_for_abandoned_pools`, and the split is
  load-bearing: that call is an `os._exit` when a probe was
  abandoned, and while it sat inside `main()` **one abandoned probe
  ended the pytest run at 40 % of the suite with exit code 0** and
  a report that read as green (LWSM-1100). Anything that ends the
  process belongs behind `run()`, never in `main()`, which tests
  call in-process. An `argparse` parser, so
  `--version` and `--help` work and an unrecognised option exits
  2 rather than being ignored. Prints where it is logging to, and
  starts anyway — with a warning on stderr — when the log
  directory cannot be used. Since P02 it also opens the window,
  via **`build_window()`** — a deliberate seam: `main()` ends in a
  blocking `app.exec()`, so anything inside it is unreachable from
  an in-process test. `QApplication` is imported and constructed
  *inside* `main`, after `argparse`, so `--version` needs no
  display.
  Since LWSM-1065 `main` also claims **`claim_single_instance`**'s socket in
  `$XDG_RUNTIME_DIR`, before logging: a second launch wakes the running copy
  and exits 0 without ever opening `app.log`, and a socket nobody answers on
  is a crashed copy's leftover and is replaced. **It sets no socket
  options** — with any set, Qt renames the socket into place and silently
  replaces a live copy's instead of failing (measured). `conftest.py` pins
  `XDG_RUNTIME_DIR`, or a test calling `main()` finds the developer's own
  open copy and returns early.
- **`src/lwsm/applog.py`** — the application log.
  `default_state_dir()`, `get_logger()`, `configure_logging()`,
  `configure_stderr_logging()` (the fallback the entry point uses
  when the file log is unavailable), and a
  `_NoFollowRotatingFileHandler` that writes only to a private
  regular file: `O_NOFOLLOW` 0600 inside a 0700 directory, and
  then an `fstat` requiring one link and our own ownership, so
  neither a symlink nor a **hard link** nor a **FIFO** planted at
  `app.log` can redirect or block the log. The last two were
  reproduced against the `O_NOFOLLOW`-only version on 2026-08-06.

Added at P02 (LWSM-1005), contract in
[`docs/specs/LWSM-1005-vertical-slice.md`](../specs/LWSM-1005-vertical-slice.md):

- **`src/lwsm/registry.py`** — core. `ProjectRecord`,
  `RegistryError`, `default_projects_path()`, `load_projects()`,
  and since LWSM-1007 also `LauncherKind`, `LoadResult`,
  `RegistryMissing`, `DETECTED_FIELDS`, `USER_FIELDS` and
  `save_projects()`; since LWSM-1385 `PortRule` and `PortFinding`,
  which records now store as `port_from` and `port_conflicts`. Returns a **`LoadResult`**, not a tuple: the file
  being unusable raises, one bad *record* never does, and
  `rows_refused` is carried **separately from `reasons`** because a
  field refusal keeps the row and only a row refusal may stop a
  write. A bad **port** loses the field, not the row. **Port ranges
  differ by field** — declared
  `port` is 1–65535 (a project may legitimately declare 80),
  `port_override` is ADR-0005's 1024–65535. Type checks use
  `type(v) is int`, because `isinstance(True, int)` is `True` and
  the file is hand-editable.
  Since LWSM-1148 it also holds the profile pair — `export_profile`,
  `merge_imported` and `user_half_applied` — on one claim: **a profile IS a
  `projects.json`**, same `schema_version`, same writer, same parser. That is
  why the item needed no format, no second parser and no migration, and why it
  was built rather than specced. The two merges are **mirrors**: a rescan
  refreshes the detected half and preserves the user half, an import does the
  reverse, and both are driven by `DETECTED_FIELDS` / `USER_FIELDS` so
  LWSM-1007 INV-1 keeps each complete. **One exception: an import never
  takes `NEVER_IMPORTED_FIELDS`** — `actions`, `launcher_override`,
  `start_at_login`, the fields that run something (LWSM-1344, LWSM-1369), and
  `health_check` / `health_path`, which decide what request is sent (LWSM-1034) —
  on either branch of `merge_imported`, nor a profile's `unknown` keys
  (LWSM-1404); the rescan's use of
  `user_half_applied` does. **`user_half_applied` takes the
  user half whole except `unknown`** (LWSM-1218; its docstring says why),
  where `_detected_half_applied` qualifies `port`: a scan's `None` means
  *unknown*, a profile's `None` is a real value. Taking the rest whole rests
  entirely on the window refusing an import whose load reported ANY refusal.
  Change one and you must change the other.
  **`export_profile`'s gate is not `save_projects`' gate**: there the risk is
  destroying a recoverable registry, here it is saving a profile that looks
  known-good and silently lost the rows the load refused.
- **`src/lwsm/health.py`** — core, no Qt at all (LWSM-1034). `ask`, the
  one place the app makes a request: an HTTP `GET` to `localhost:<port>`
  through `http.client`, which follows no redirect, returning the status code
  or None. The controller schedules it every `HEALTH_INTERVAL_MS` on its own
  pool; the page is validated by `registry.health_path_ok` before it gets here.
- **`src/lwsm/ports.py`** — core, no Qt at all. `PortProbe`,
  `PortSnapshot`, `ProbeError`, and the `SupportsSnapshot`
  Protocol the controller accepts so test fakes are the contract.
  One `psutil.net_connections` call per snapshot.
- **`src/lwsm/controller.py`** — core, `QtCore` only.
  `ProjectController`, `ProjectStatus`, `RowView`. Since LWSM-1010
  it also drives the buttons: `start_project`, `stop_project`,
  `restart_project`, and the **optimistic overlay**. **The overlay
  settles on the state it was heading *for*** — `starting` on
  running, `stopping` on stopped — never on any derived state:
  `design.md § State management` contains both readings, and only
  this one makes "a slow start keeps the overlay" true, since a
  server that has not finished binding reads as *stopped*. Polls every
  1000 ms **on a `QThreadPool` worker** (design.md § State
  management requires it). **`QRunnable` is not a `QObject`**, so
  the task holds a composed `_SnapshotSignals(QObject)` — a
  `Signal` declared on a bare `QRunnable` has no `emit`.
  `stop()` waits for the pool, and every test fixture calls it. Its bounded-wait
  escape is **`abandon_pool`**, public since LWSM-1139 because the window's
  rescan pool needs the identical two lines and a second copy that forgot the
  `setParent(None)` would look right and hang on exit. **Nothing in a tick
  asks the OS on the GUI thread** (LWSM-1401). The reap, the log rotation
  (LWSM-1136) and the process-group walk run as **`_do_upkeep`** on their own
  one-thread pool. That pool sits outside the snapshot's in-flight guard,
  since a log cap that lapses when the socket table is slow is not a cap. Its
  slot starts the snapshot, so a released slot is known before the snapshot
  that reads it. **`_resolve_holders`** finds each holder's unit and ADR-0003's
  `systemctl` binding inside the snapshot task; `_classify` only reads the
  answers. `RowView` carries
  **`managed`**, read once per render from `supervisor.running()`, because
  ADR-0004 derives state from the socket table and `status` therefore cannot say
  whose server it is.
- **`src/lwsm/configfile.py`** — core. `ConfigFileError`,
  `MAX_FILE_BYTES`, `MAX_REASON_CHARS`, `quoted()`, `read_bounded()`,
  `prepare_config_dir()`, `refuse_existing_target()`,
  `write_atomically()`, and **`load_json_object()`**: the one JSON
  config reader, used by `registry`, `settings` and the trust store, which
  raises `JsonFileRefused` naming the stage that failed so each caller keeps
  its own wording (LWSM-1357), and **`BoundedReasons`**, the capped reason
  list with its "and N more, not shown" tail that the scanner, the
  registry load, the merge and the import all use (LWSM-1361). **Extracted from `registry.py` by LWSM-1031,
  which needed a second config file** — every function in it was written
  after a measured defect (a FIFO that made the read block forever with no
  window and no log line, a symlink destroyed by `os.replace`, a
  `mkdir(parents=True, mode=0o700)` leaving every parent at the umask
  default, a 600 MB file peaking at 1214 MB RSS), so a second weaker copy
  for `settings.json` is what `coding.md § 1.3` forbids. `RegistryError`
  subclasses `ConfigFileError` and `save_projects` **converts rather than
  propagating**, because its contract and four tests promise the narrow
  type and `except RegistryError` does not catch a base-class instance.
- **`src/lwsm/settings.py`** — core, no Qt. `Settings`, `LoadResult`,
  `SettingsError`, `default_settings_path()`, `load()`, `save()`.
  Minimal by design: `schema_version` plus the theme id, on the file
  **LWSM-1018 grows**. **`load()` never raises** — that is the one rule
  separating it from `registry.py`: a project list nobody can parse is a
  refusal the user must see, because the alternative is inventing projects
  (ADR-0005), while a preference nobody can parse has an obvious right
  answer. Every refusal still reports a reason, and `build_window` puts
  those in the status bar; a mutant logging them and never showing them
  survived every other test. It **does not check that a theme id names a
  theme** — a core module may not import `theme.py` (`§ O1`), and
  `theme.theme_for_id` owns the fallback.
- **`src/lwsm/appearance.py`** — core, no Qt at all. `high_contrast()`, and
  that is the whole surface. Added by LWSM-1244 for **Follow system**, and it
  holds the contrast preference alone because Qt already reports light/dark
  itself, live, through `QStyleHints`. Qt has no counterpart for contrast:
  measured against the pinned PySide6, the `ContrastPreference` enum exists
  and no accessor returns one, so the XDG settings portal is the only route.
  Read over `dbus-send`, which `placement.py` already needs — which is why
  no D-Bus binding is a dependency. **Every failure answers False**, because
  a wrong True forces an assistive palette on someone who never asked and a
  wrong False leaves them where they already were.
- **`src/lwsm/placement.py`** — core, and like `ports.py` imports **no Qt
  at all**, not even `QtCore`: the arithmetic in it is ADR-0007's security
  boundary, and a boundary is worth testing with no display. `Rect`,
  `clamp_to_screens`, `centre_in`, `pair_or_none`, `on_wayland`,
  `placement_available`, `position_is_readable`, `kwin_script`,
  `run_kwin_script`, `place_window`. Added by LWSM-1033; the technique is
  transcribed from `OneUp/oneup/gui/placement.py`, **not** the
  `OneUp/updater.py` lines ADR-0007 once cited, which stopped resolving and
  were removed (LWSM-1060). **Restoring a position and centring are one operation
  with two targets**, so both go through `place_window` and the clamp cannot
  be forgotten by either. **Setting a position and READING one are not
  symmetric** — see the Wayland trap below, which is the item's whole shape.
- **`src/lwsm/theme.py`** — UI layer, and the **only** module
  allowed a colour literal; `test_layering.py` exempts it by an
  explicit allowlist and asserts it still holds the palette.
  Since LWSM-1031 it holds **eight palettes** — `THEMES`, `DEFAULT_THEME`
  (`midnight`, LWSM-1147) and `theme_for_id()`. The six are **transcribed**
  from `finbreak/src/finbreak/ui/theme.py`, never imported: a public repo
  cannot depend on a path outside it. **Every state token was solved for,
  not chosen** — a fixed hue per meaning, lightness walked *away* from the
  palette's surfaces until the worst of `window`/`base`/`alt_base` clears
  the floor, then stopped. **Walking from the far end instead returns
  near-white for every hue on a dark palette**, which is legible and
  carries no meaning at all; that draft passed every contrast check, which
  is why `test_the_state_tokens_are_distinguishable_from_the_body_text`
  exists. Four `muted_text` values diverge from finbreak, each recorded
  beside its value: finbreak tuned them against `window` alone and
  `alt_base` is darker. `high_contrast` is a flag **on the theme** rather
  than a set of ids beside it, because the floor a palette is judged
  against is a property of the palette. **It also owns `OutlineStyle`**
  (LWSM-1337, LWSM-1349), a proxy over Fusion that paints each control's
  outline in `Mid` and a thick focus ring in `Highlight` after Fusion has
  drawn, so the shading stays; `install_outline_style` puts it on the
  application, before the palette. `focus_ring_width` is the one ring-width
  formula, shared with the row.
- **`src/lwsm/mainwindow.py`** — UI layer.
  Since LWSM-1033 it also owns
  **window geometry and Centre on screen** — `showEvent`/`eventFilter`,
  `_restore_geometry`, `closeEvent`, `centre_on_screen`, `_place_at`,
  `_screens` and two injected seams (`save_geometry`, which defaults to doing
  NOTHING for `save_theme`'s reason, and `place`, which defaults to the real
  function because ADR-0007 requires the verification to be behavioural).
  **The seams are named, never numbered**: the ordinals fell out of step with
  the constructor, which injects more than any count written down (LWSM-1281). **What is stored is a FRAME corner and a
  CLIENT size**, because those are what `move()` and `resize()` round-trip
  exactly; storing `normalGeometry()`'s corner and restoring it through
  `move()` walks the window two pixels down and right on every launch
  (measured). `normalGeometry`, never `geometry`, or a maximised window
  reopens filling the screen without being maximised — which the user cannot
  undo with the maximise button. The **View** menu is a third top-level menu
  for one action on purpose: "Centre on screen" is a verb, and every entry in
  Settings is a choice that then stays chosen.
  Since LWSM-1131 it also
  owns the **Rescan** seam: `RescanContext` (scan roots, the scan
  function and the clock, all injected so `testing-overrides.md § T1` holds; the
  writer is `registry.ProjectsFile`, which every writer shares, LWSM-1358),
  `summarise_merge`, and a `_RescanTask` on its own `QThreadPool`.
  **The write happens in the slot, never in `merge()`** — the merge
  runs on the pool thread and is handed no `LoadResult`, so the
  window is the only place the records and LWSM-1007's read-only
  gate are both in scope. Rows are created once
  and **updated in place**; rebuilding would drop keyboard focus
  and re-announce every unchanged row. The state glyph is
  decorative and excluded from the accessible name, which is
  built from the rendered cell strings.
  Since P04 it also owns the **layout**: `_align_columns` (LWSM-1145)
  and `_apply_default_geometry` (LWSM-1149), with `DEFAULT_VISIBLE_ROWS`
  and `MIN_VISIBLE_ROWS` as **counts of rows, never pixels** (`§ O7`).
  **Qt syncs nothing between sibling layouts** — each `ProjectRow` owns
  its own `QHBoxLayout`, which is why every row's buttons landed at a
  different x. One width per column, the widest cell winning, re-run
  after every `_sync_rows` and after a language or font change; it
  cannot be settled at construction, because rows are updated in place.
  `natural_widths` reads the rendered text and the stored floors and
  **never `minimumWidth()`** — `apply_column_widths` sets a FIXED width,
  so reading it back makes the column monotonic: it grows for a
  long-named project and never shrinks when that project leaves.
  The row list sits in a **`QScrollArea`**, which was not in LWSM-1149's
  filed scope and is the part that mattered most: without it the
  window's minimum height is every row it holds, so twenty projects give
  a window taller than the screen that cannot be shrunk.
  Since LWSM-1031 it also owns the **theme picker** — `_build_theme_menu`,
  `set_theme` and `ProjectRow.apply_theme`. **The swap goes to the
  APPLICATION palette, the window's style sheet and then every row**, which
  is the same three places `__init__` applies it and for the same reasons:
  a `self.setPalette` themes the frame and nothing inside it (LWSM-1118),
  and a row caches its own `Theme` **and its glyph colour**. LWSM-1111
  named that cache as the live edge the day the palette could change and
  predicted the fix would look like `retranslate()` — it does, both going
  through `_rerender`. **`save_theme` is an injected seam defaulting to doing
  NOTHING**: `confirm` and `open_url` default to
  the real behaviour safely because an untriggered test never reaches
  them, while this one would write to the developer's own `settings.json`
  the moment a test exercised the picker.
  Since LWSM-1146 it also owns the **menu bar** — `_build_menus`,
  `_retranslate_menus` and `_set_rescan_enabled`. It owns the BAR only; the
  settings dialog is LWSM-1018's and arrives through the injected
  **`open_settings`** seam, the same shape as `confirm` and `open_url`. Every label carries an `&` mnemonic so the bar is keyboard-
  reachable before LWSM-1040 lands, and the labels are set in
  `_retranslate_menus` rather than at construction so `LanguageChange` has one
  place to go. **The menu bar counts as chrome in `_apply_default_geometry`** —
  leave it out and the window opens one bar too short, so a list that fits
  scrolls; two LWSM-1149 geometry tests die on that mutant. Rescan is one
  control with two faces, which is why the enable/disable is a helper and not
  two call sites.
  Since LWSM-1139 **`shutdown()` is `controller.stop()`'s shape, both halves**:
  it sets `_stopped` (checked by `_on_rescan_done` and `_on_rescan_failed`, so a
  merge landing after teardown cannot save over the project list) and it TAKES
  the pool, waits, and hands a timed-out one to `abandon_pool`. Logging the word
  "abandoning" and returning leaves the pool parented, so `~QThreadPool` runs
  the unbounded join anyway — the claim in `__main__` was false for a day.
  **`update_from`'s announcement is gated on the accessible NAME, not on
  `RowView` equality** (LWSM-1141): `managed` is the first field that renders as
  button enablement and as no text at all, so the view can change while nothing
  a screen reader reads out does. Any future non-textual field inherits that.
  Since LWSM-1040 it also owns **keyboard-first navigation** — `_filter`,
  `_apply_filter`, `_ordered_rows`, `_retranslate_filter` and the window's
  `keyPressEvent`, with `ProjectRow.matches` and `ProjectRow.keyPressEvent` on
  the row. **The filter box SHARES the Rescan strip** (user decision,
  2026-08-19) rather than taking a second one: every row of chrome is a row the
  list does not get, and `_apply_default_geometry` therefore measures the
  **strip**, not the button in it. The strip is now unconditional, because the
  filter is there whether or not the window has anything to rescan.
  **The two mechanisms share one keyboard by relying on Qt's propagation, not
  on a guard**: a `QLineEdit` consumes every digit and `/`, so typing `1` into
  the filter types rather than jumping, and no line in `keyPressEvent` says so.
  Escape is the deliberate exception — `QLineEdit` ignores it, which is what
  lets one handler clear the filter from inside the box and from anywhere else.
  **Enter CLICKS the row's enabled button** rather than calling the controller,
  so which action is legal in which state stays stated once in
  `_apply_button_state`; both overlay states disable Start and Stop together,
  so Enter does nothing mid-transition without naming a state.
  **Filtering hides rows, never rebuilds them** (INV-13), and `_sync_rows`
  re-applies the filter so a rescan cannot land a project into a list the user
  has narrowed.
  Since LWSM-1148 it also owns **profile export and import** — `_export_profile`,
  `_import_profile`, `summarise_import` and two injected seams,
  `choose_profile_to_save` / `choose_profile_to_open` (a real `QFileDialog` in a
  test hangs the run, which is `choose_directory`'s reason). **Both File-menu
  entries appear or neither**: exporting needs the `LoadResult` its gate reads
  and importing needs somewhere to write back to, so one condition covers both
  and states nothing untrue. **Import is disabled while a rescan is in flight**
  and export is not — a rescan that started first writes last, so a restored
  user half would be silently dropped; export only reads. `_apply_rescan`'s body
  became **`_apply_merge`**, shared by both, because the write gate, the
  `RegistryError` handling and the `self._load` refresh after a successful write
  are the same three rules either way — and a second copy is a second place to
  forget the refresh.

Added at P03 (LWSM-1006, which also lands LWSM-1050), contract in
[`docs/specs/LWSM-1006-scanner-detection.md`](../specs/LWSM-1006-scanner-detection.md):

- **`src/lwsm/scanner.py`** — core, no Qt at all, like `ports.py`.
  `scan()`, `DetectedProject`, `ScanResult`,
  `Confidence`, `Deadline`, and the
  `SupportsUnitLookup` Protocol the systemd surface is injected
  through. **`LauncherKind` moved to `registry.py` with LWSM-1007**,
  and `PortRule` and `PortFinding` with LWSM-1385; all three are
  re-exported from here, so `scanner.LauncherKind` still
  resolves; the direction is `scanner` → `registry` and adding the
  reverse import stops the package importing at all, on either entry
  order. `tests/test_layering.py` asserts that by AST. **Everything it reads belongs to somebody else**, so
  every open goes through **one** function, `_open_source`
  (`O_RDONLY|O_NONBLOCK|O_NOFOLLOW`) — that single seam is what the
  tests patch to prove no file outside a candidate is ever touched.
  `port is None` means *unknown*; it is never a guess.
  **`CORE_MODULES` in `tests/test_layering.py` now covers
  `applog.py` too**, and a source-invariant test fails on any file in
  `src/lwsm/` that is in neither `CORE_MODULES` nor `NON_CORE_MODULES`.
  Both lists are written by hand: a new module goes into one of them,
  and editing `coding-overrides.md § O1` alone changes nothing the test reads
  (LWSM-1335).
- **`src/lwsm/scanroots.py`** — core, no Qt. The scan-roots file that
  says which directories a Rescan walks: `default_scan_roots()`,
  `save_scan_roots()`, `scan_roots_path()`, `scan_root_fallback()`, and
  `_is_root_line()`, the one statement of which lines are directories.
  Moved out of `__main__.py` (LWSM-1359), where the reader and the writer
  each spelled that rule out.

Added at P05 (LWSM-1009, which also lands LWSM-1048 and the core
halves of LWSM-1046 and LWSM-1047). **No spec** — the first item
built under § Review cadence's build-first default:

- **`src/lwsm/supervisor.py`** — core, no Qt at all, like
  `ports.py`; stop needs a worker thread and a plain
  `ThreadPoolExecutor` is enough for one. `Supervisor`,
  `ManagedProcess`, `StopOutcome`, `TrustStore`,
  `build_child_env`, `validate_launcher`, `launcher_fingerprint`,
  and the refusals `LauncherRefused` / `LauncherUntrusted` /
  `PortAlreadyBound` / `AlreadyRunning`. **Stop signals the process
  *group*, not the descendants** — a launcher that double-forks
  leaves a server reparented to init, which `Process.children()`
  can no longer see while `start_new_session=True` guarantees it is
  still in the group. Every signal goes through a `psutil.Process`
  handle **captured at spawn**, which is what lets
  `_raise_if_pid_reused` fire at all. **Log rotation copies and
  truncates rather than renaming**, because the child holds a
  duplicate of our descriptor and a rename would leave it writing
  into an unlinked inode — which is also why the log is opened
  `O_RDWR` rather than `O_WRONLY`. **Which file an argv names is
  decided by POSIX, not by path arithmetic**: `_launcher_path`
  returns the script for `./start.sh`, `python3 serve.py` and
  `node serve.mjs`, and `None` for `npm run <script>`, whose
  untrusted content is a string inside `package.json` that
  `launcher_fingerprint` hashes under its own marker
  (LWSM-1132, LWSM-1140). **Both halves of the registry are guarded under the
  lock across the whole operation, not at one end of it** (LWSM-1137/1138):
  `start()` RESERVES the key in `_Registry.starting` before it releases the lock
  for the pre-flight, the trust gate, the log open and the spawn — a set beside
  `processes` rather than a sentinel inside it, so `running()`, `_get` and
  `exited()` never see a row that is not a `ManagedProcess` — and `stop()` POPS
  the entry before it signals anything, so whoever pops owns the sequence and
  the log descriptor is closed exactly once. The reservation's discard lives in
  a `finally`: one that only ran on success would turn a single refused start
  into a project that can never start again this session.
  **Popping is not RESERVING, and for a while `stop()` only popped**
  (LWSM-1168) — the grace, kill and reap window ran with the project in
  neither map, so a Start arriving inside it passed the pre-flight and spawned
  a second child, after which the in-flight stop killed the old group and the
  manager reported its own new server as a stranger's. Reproduced by holding
  the window open at the `_on_wait` seam rather than racing for it. `stop()`
  now holds the key in `_Registry.stopping` for the whole sequence, discarded
  in the same `finally` shape and for the same reason. It gates `start()`
  alone: a second `stop()` still finds nothing and returns an empty outcome,
  which is what makes stop() idempotent.

Added at P04 (LWSM-1018). **No spec** — build-first, per § Review cadence:

- **`src/lwsm/settingsdialog.py`** — UI layer. `SettingsDialog`,
  `keyboard_focus_order`. **It edits three fields, not the four the bullet
  filed**, and both absences were settled with the user (2026-08-21) rather
  than dropped: *scan roots* stay in the `scan-roots` file (LWSM-1144) and the
  dialog edits that file in place, because copying them into `settings.json`
  buys a migration and a second owner for no user-visible gain; and there is no
  *slow-start threshold* to configure, because ADR-0004 § Slowness is not
  failure deleted the 15-second `starting` deadline on measured evidence, so a
  setting for it would re-introduce the defect that ADR reversed.
  **The dialog owns no I/O** — it is handed values and returns values, and
  `build_window` is the only scope where both config files and both live
  objects are in reach, which is what the `open_settings` seam was left for
  (LWSM-1146). `choose_directory` is an injected seam, for `confirm`'s
  reason: a real `QFileDialog` in a test hangs the run.
  **Both numbers apply without a restart** — `QTimer.setInterval` is honoured
  on a live timer, and `rotate_if_needed` re-reads `Supervisor.max_log_bytes`
  each poll. `settings.py` owns both defaults and `controller.POLL_INTERVAL_MS`
  / `supervisor.MAX_LOG_BYTES` are aliases of them, so the file's default and
  the code's default cannot drift.
  **A saved scan-roots file keeps the user's LEADING comment block and loses
  interleaved ones** — a stated loss, pinned by a test: re-attaching a comment
  to the wrong surviving line is worse than dropping it.

Added for LWSM-1008. **No spec** — build-first, per § Review cadence:

- **`src/lwsm/firstrun.py`** — UI layer. `FirstRunDialog`, `ask_first_run`,
  `describe`. With no `projects.json` yet, the first scan's projects are
  listed here, each ticked, before anything is written; Save returns the
  ticked records and Not now returns `None`, never `[]`, which would save an
  empty list. **It owns no I/O**: `MainWindow._apply_rescan` calls it through
  the injected `confirm_first_run` seam and writes through `_apply_merge`.
  `__main__.start_first_run` starts the scan once the window is shown, and asks
  for a folder first when no scan root exists.

Added later, both core with no Qt at all:

- **`src/lwsm/browsers.py`** (LWSM-1187) — the desktop's own registered
  `x-scheme-handler/http` handlers, and opening a URL in one. **It runs no
  command the user typed**: the candidates are entries this session would
  already run for a clicked link, so a per-project browser adds no surface
  ADR-0003's trust gate would have to cover.
- **`src/lwsm/service.py`** — ADR-0003's second column: a project whose server
  is a systemd **user** unit is driven with `systemctl --user`, never by
  spawning its launcher, and nothing here signals a process. It also writes
  this app's drop-in (`50-lwsm-port.conf`) before a start and removes it after
  each successful or rejected verb: the one file this app writes outside its
  own config (LWSM-1028, LWSM-1387, L05-M3).
- **`src/lwsm/foreign.py`** — ADR-0004's foreign stop, for a server in no
  systemd unit (LWSM-1301): the holder and its descendants, identified by
  PID and start time, and signalled as exactly that set through
  `psutil.Process` handles. No Qt. The window shows the set, re-enumerates
  it after the user's yes, and asks again if it changed.

Tests: `ls tests/` is the list, and it is deliberately not copied here — a
copy fell behind and read as complete (LWSM-1303). Most files are
`test_<module>.py` for the module of that name. The ones a name does not
explain: `test_layering.py` (the source invariants — `§ O1`'s layering, the
colour allowlist, no `str.format` on translated text), `test_docs.py` (prose
invariants, fired by the shape of a past defect), `test_translatable.py` (every
translated string is one `lupdate` can see), `test_local_release.py`,
`test_desktop_entry.py` and `test_derive_state_tokens.py` (the scripts of those
names), `contrast.py` (WCAG arithmetic shared by the theme tests, named so
pytest imports rather than collects it),
`test_ci_contract.py` (the gate's own contract — that `ci.yml` adds no
check of its own, that both sides install the versions
`scripts/ci-tools.env` pins, and that the `pre-push` hook is present,
executable and does not exempt the gate's own inputs) (+ `scanner_fixtures.py`,
the detection regression corpus every future mis-detection is
added to), plus `conftest.py` (sets
`QT_QPA_PLATFORM=offscreen` when unset, so a bare `pytest` cannot
open a real window, and **pins `XDG_CONFIG_HOME` to a fresh directory
per test** — since LWSM-1031 `build_window` reads `settings.json`, and
three `build_window` tests pin only `projects_path`, so without this they
pass or fail depending on which palette the author last chose in the real
app; and since LWSM-1033 **pins `XDG_SESSION_TYPE` to `x11`**, because
`placement.py` branches on it — this machine runs Wayland and the CI runner
has it unset, so an unpinned test asserting either branch passes on one
and fails on the other). **Markers go on tests, not files** — marking
a whole file by its heaviest test makes `--fast` silently skip
every light test beside it.
