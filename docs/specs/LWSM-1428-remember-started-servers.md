<!-- ants-spec-format: 1 -->
# LWSM-1428 — Remember the servers this app started

**Status:** accepted (2026-10-29).
**Kind:** implement.
**Source:** ROADMAP LWSM-1428 (user-2026-10-29).
**Amends:** [ADR-0004](../decisions/0004-runtime-truth-from-probing.md)'s
"Nothing about runtime state is persisted".

After you close and reopen the app, a site it started still reads `running`,
with Stop and Restart, instead of `running (foreign)`.

## 1. Goal

After this ships, the supervisor writes each server it starts to
`started.json` in the app's state directory, and removes it when the server
stops or its process group is gone. On the next launch, each entry whose
launcher is still the same process is taken back as the supervisor's own. The
controller then classifies that project exactly as it would a child started in
this session.

## 2. Problem

1. **A relaunch forgets every child.** `Supervisor.close` leaves servers
   running (ADR-0003), and `Supervisor._registry.processes` starts empty. A
   server this app started in an earlier session is held by a group the new
   session has no entry for, so `ProjectController._classify` reads it as
   `running (foreign)`.
2. **A foreign row has no Restart.** ADR-0004 withholds Restart from a foreign
   server, because nothing shows it was started by the project's launcher. For
   a server the app itself started, that caution is wrong. Reported by the
   user on RetroDB, 2026-10-29.

## 3. Scope decisions (agreed with the user)

- **Record each start, and use the record on relaunch** (user, 2026-10-29).
- **No `review-contract` gate on this spec or the ADR-0004 amendment** (user,
  2026-10-29: "no review is needed, this isn't a complicated task").
- **Identity is the launcher's PID plus its `create_time`**, the identity
  ADR-0004 already names for a managed server. Chosen in drafting, not by the
  user: anything weaker could call a stranger ours.

## 4. Design

### 4.1 The file

`$XDG_STATE_HOME/localwebservermanager/started.json`, from
`applog.default_state_dir()`. State, not config: it records what happened, and
`coding-overrides.md` § O3 puts that under the state directory.

```json
{
  "schema_version": 1,
  "started": [
    {"project": "/abs/path", "name": "RetroDB", "pid": 2345212,
     "create_time": 1761734512.43, "port": 5000,
     "since_boot": 81234.56, "boot_id": "fb6c764c-…"}
  ]
}
```

- `project`: the resolved absolute path, the supervisor's key.
- `name`: the display name, used only to rebuild the log path through
  `Supervisor.log_path_for`. No path is read from the file.
- `pid`: the launcher's PID, which `start_new_session=True` also makes the
  process-group id.
- `create_time`: `psutil.Process.create_time()` taken at spawn.
- `port`: the port passed as `PORT`, or `null`.
- `since_boot` and `boot_id` (LWSM-1448): the start in seconds since boot,
  to the kernel's 0.01 s tick, and `/proc/sys/kernel/random/boot_id`. Both
  or neither; a file written before them has neither. `schema_version` stays
  1: the fields are additive, and a reader that does not know them ignores
  them.

`create_time` is wall clock: psutil adds the boot time, read from
`/proc/stat` on every call, to the start's ticks since boot. A clock step
moves the boot time, so one process's `create_time` changes (psutil's own
`boot_time` docstring says so). `since_boot` does not move, and `boot_id`
tells a reboot apart, after which no stored PID can be the one started.

Written whole through `configfile.write_atomically` after every change. With no
path, the store is memory only, as `TrustStore` is; every test's `Supervisor`
gets that.

### 4.2 Writes

| Event | Entry |
|---|---|
| `start()` spawns a child | added, replacing any entry for that project |
| `stop()` pops the project | removed |
| `reap_exited()` drops the project | removed |
| `adopt()` refuses the entry | removed |
| `close()` | kept: the servers outlive the app |

### 4.3 Adoption

`Supervisor.adopt()` runs once, from `__main__.build_window`, before the first
poll. For each entry it builds a `psutil.Process(pid)` and takes the entry only
if all of these hold:

1. The process exists and is the one started. With `since_boot` and
   `boot_id` stored: `boot_id` is this boot's, and the process's start since
   boot equals `since_boot`. Without them: its `create_time()` equals the
   stored one.
2. `os.getpgid(pid) == pid`: it is still the leader of the group it was
   started in.
3. The project is not already in the registry, nor held by a start or stop
   in flight (LWSM-1442).

A taken entry becomes a `ManagedProcess` with `popen=None`, the handle from
step 1, and a log descriptor opened on `log_path_for(project, name)`. Every
other entry is dropped, and the file rewritten once if anything was dropped.

### 4.4 A `ManagedProcess` with no `Popen`

An adopted launcher is not this process's child, so it cannot be waited on.

- `ManagedProcess.pid` reads `handle.pid`, which equals `popen.pid` for a
  spawned child.
- `_reap` skips the wait and returns exit code `None`. It still closes the log
  descriptor.
- `close()` skips the poll.
- `owns_pid` skips its `is_running()` gate on the leader, which an
  adopted leader fails as soon as its new parent reaps it (LWSM-1437).
  Once the leader is gone it walks the group instead (LWSM-1494; the
  argument below).
- `_group_members` keeps an adopted group only while it can vouch for it.
  `vouched_at` is the last moment the group was seen occupied: when the
  leader passed adoption's checks, or was seen alive since. A walk that
  finds a member started before `vouched_at`, less one start-time tick,
  moves `vouched_at` to the walk. A walk that finds none returns no members.

Everything else — `stop`, `exited`, `group_alive`, `reap_exited`,
`rotate_if_needed` — reads the handle, the group or the log descriptor, and
is unchanged.

**The PID-reuse argument changes for an adopted group.** For a spawned child,
the unreaped leader keeps its PID reserved through the stop. An adopted leader
is reaped by its new parent the moment it exits. Linux does not reissue a PID
still in use as a process-group id, so the number stays reserved while any
member lives. Once the whole group is gone, the id can be reissued, and the
entry outlives the group until the next `reap_exited`. The id alone then
cannot tell a stranger's group from ours (LWSM-1494). A member started before
`vouched_at` can: it lived through the whole gap, so the group never emptied.
With none, the group is treated as ended. That can disown a server whose
every older process exited within one tick, leaving only a newer one; the
safe direction. Every signal still goes through a `psutil.Process` handle,
which refuses a reused PID.

## 5. Invariants

- **INV-1** — A started child is recorded with its launcher's PID and `create_time`.
  *Test:* `tests/test_supervisor.py::test_a_start_is_recorded_and_a_stop_forgets_it`.
  *Breaks when:* `start()` spawns without writing the entry, or writes another PID.

- **INV-2** — A stop, or a group found gone, removes the entry.
  *Test:* `tests/test_supervisor.py::test_a_start_is_recorded_and_a_stop_forgets_it`,
  `::test_a_group_that_ended_on_its_own_is_forgotten`.
  *Breaks when:* `stop()` or `reap_exited()` leaves the entry, so a later launch
  tries to adopt a dead server.

- **INV-3** — Adoption takes an entry only when PID, `create_time` and group all
  match.
  *Test:* `tests/test_supervisor.py::test_adoption_takes_only_the_same_process`.
  *Breaks when:* an entry whose PID now names another process, or a process that
  left its group, is taken as ours.

- **INV-4** — A refused, unreadable or malformed record adopts nothing and raises
nothing.
  *Test:* `tests/test_supervisor.py::test_a_bad_record_adopts_nothing`.
  *Breaks when:* a bad file stops the app opening, or a malformed entry is taken.

- **INV-5** — An adopted project is ours to the controller.
  *Test:* `tests/test_supervisor.py::test_an_adopted_server_is_owned_and_stops`,
  `::test_an_adopted_server_stays_ours_after_its_launcher_exits`.
  *Breaks when:* an adopted project still reads `running (foreign)`, including
  after its launcher exits, or Restart is not offered on it.

- **INV-6** — An adopted group is stopped through the group, and its entry released.
  *Test:* `tests/test_supervisor.py::test_an_adopted_server_is_owned_and_stops`.
  *Breaks when:* `stop()` waits on a missing `Popen`, or leaves the group running.

- **INV-7** — An adopted group id reissued after the group ended is not ours
  (LWSM-1494).
  *Test:* `tests/test_supervisor.py::test_an_adopted_group_id_reissued_after_the_group_ended_is_not_ours`.
  *Breaks when:* a process in the reissued group is owned, kept alive by
  `group_alive`, or keeps the entry through `reap_exited`.

- **INV-8** — A clock step between sessions does not refuse our own server,
  and a reboot refuses every entry recorded before it (LWSM-1448).
  *Test:* `tests/test_supervisor.py::test_a_clock_step_between_sessions_still_adopts`,
  `::test_an_entry_from_another_boot_is_not_adopted`.
  *Breaks when:* adoption compares the wall-clock `create_time` where
  `since_boot` is stored, or ignores `boot_id`.

## 6. Failure modes

- **The file cannot be read, or is malformed.** Logged; nothing is adopted;
  those servers read `running (foreign)`, as before this item (INV-4).
- **The file cannot be written.** Logged. The session runs as before; the next
  launch may see a stale entry, which step 1 of § 4.3 refuses once the process
  is gone.
- **A launcher that forks its server and exits.** Its PID is gone by the next
  launch, so the entry is refused and the server reads `running (foreign)`.
  Accepted: without the launcher, nothing distinguishes our group from a
  stranger's.
- **Two instances of the app.** The last writer wins, as for `trust.json`.

## 7. Tests

- `tests/test_supervisor.py` — INV-1 to INV-8.

The invariants' *Test:* lines name each test. Every test spawns real children in
its own session and uses a `started.json` under the test's private
`XDG_STATE_HOME`.

## 8. Alternatives considered (and rejected)

- **Adopt by the working directory of the port holder.** Rejected:
  ADR-0004 rules the working directory out as identity for a managed server.
- **Adopt a group whose leader has exited.** Rejected: with the leader gone
  there is no `create_time` to compare, so the group could be a stranger's.
- **Record at shutdown only.** Rejected: a crash or a killed app would record
  nothing.

## 9. Out of scope

- Starting the recorded servers on launch — LWSM-1035, which may reuse this
  file.
- Restart on a truly foreign row: ADR-0004's rule stands for servers this app
  did not start.

## 10. What checks this

| Clause | What checks it |
|---|---|
| INV-1 to INV-8 | the tests named on each |
| § 4.4 PID-reuse argument | INV-7's test, with the reissue simulated |
| § 4.1 no path read from the file | **nothing mechanical** — read in review |

## 11. Cross-doc impact

- ADR-0004 § Decision's "Nothing about runtime state is persisted" names this
  file as the one exception.
- `docs/claude/module-map.md`'s `stores.py` entry names the record (moved
  from `supervisor.py` by LWSM-1492).

## 12. Cold-eyes loop log

Rows live in `../reviews/LWSM-1428-remember-started-servers-loop-log.md`.
