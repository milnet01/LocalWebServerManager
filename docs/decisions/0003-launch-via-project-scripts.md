# ADR-0003: Launch sibling scripts via `subprocess` in a new session

- **Status:** Accepted
- **Date:** 2026-08-03
- **Deciders:** Project lead
- **Related:** [ADR-0002](0002-port-contract.md),
  [ADR-0004](0004-runtime-truth-from-probing.md)

## Context

The manager starts each sibling project by running **that
project's own launcher** — `./start.sh`, `./run.sh`,
`python3 serve.py`, `node serve.mjs`, `npm run dev` — so no
sibling has to change and each project's own setup work
(virtualenv creation, dependency install) still happens.

Those launchers are almost all **wrappers**: `start.sh` runs a
Python process as a child. Killing only the launcher leaves the
real server alive and still holding the port — the precise
failure this app exists to prevent. Stopping therefore has to
signal the whole **process group**, not one PID.

`docs/discovery.md` named Qt's `QProcess` for this. Verified on
this machine on 2026-08-03: **PySide6 6.11 does not expose
`QProcess.setChildProcessModifier`** (`hasattr(QProcess,
'setChildProcessModifier')` → `False`), which is the only hook
Qt offers for placing a child in a new session. Without it, a
`QProcess` child shares the manager's own process group, so a
group-kill would kill the manager. `QProcess` cannot meet the
requirement in this binding.

Alternatives considered:

- **`QProcess` running `setsid --wait <launcher>`.** Works, but
  `processId()` then returns `setsid`'s PID while the session
  leader is its child, so the manager must re-derive the group
  through `psutil` on every stop. Indirection for no gain.
- **`QProcess` with a single-PID kill.** Rejected: leaves
  orphaned servers holding ports.

## Decision

**Spawn launchers with Python's `subprocess.Popen(...,
start_new_session=True)`, and stop them by signalling the process
group.**

Specifics:

- `start_new_session=True` puts the child in a new session and
  process group whose **group ID equals the child's PID**, so the
  manager can signal the whole tree with
  `os.killpg(child.pid, ...)` and can never signal its own group.
- The launcher is invoked as an **argument vector** (`["./start.sh"]`,
  `["npm", "run", "dev"]`) with `shell=False`, `cwd` set to the
  project directory. No string this app builds is handed to a shell.
  **This is not injection immunity, and an earlier version of this
  ADR wrongly claimed it was** (security review, 2026-08-03): a
  launcher *is* a shell script, and `npm run <script>` executes the
  `scripts.dev` **string** from an untrusted `package.json` through
  `/bin/sh`. Running a discovered launcher is running arbitrary code
  by nature — see § Trust below.
- **The child's environment is an allowlist, not an inheritance.**
  `PATH HOME USER LOGNAME SHELL LANG LC_* TERM TZ XDG_RUNTIME_DIR
  XDG_SESSION_TYPE DISPLAY WAYLAND_DISPLAY DBUS_SESSION_BUS_ADDRESS`,
  plus `PORT` (ADR-0002) and `LWSM_MANAGED` (ADR-0006). Passing
  `os.environ` through would hand every scanned project —
  including a hostile one — `SSH_AUTH_SOCK` (a live signing
  oracle), API keys and cloud credentials, all readable afterwards
  from `/proc/<pid>/environ` by any other local process. A manager
  that starts things on your behalf must not also be a credential
  broker.

### Trust: a discovered launcher is untrusted until confirmed

Anything in a scan root is auto-listed, and a hostile directory —
cloned, unzipped, or written by another project's `postinstall` —
is visually indistinguishable from a real project. One click then
runs it as the user, and start-at-login (LWSM-1027) makes that zero
clicks at every login.

So **Start is gated by a one-time per-project confirmation** showing
the resolved absolute launcher path and the exact argv. The gate
**re-arms** whenever the launcher command or its content hash
changes — ADR-0005's merge already detects *Changed*, so this reuses
a signal that exists rather than adding one. A launcher that is a
symlink pointing outside its project, or that is group- or
other-writable, is refused outright.

The confirmation is not security theatre only if it shows what will
actually run: the resolved path and argv, never a friendly summary.
- stdout and stderr are **merged and redirected to a per-project
  file** under `$XDG_STATE_HOME/localwebservermanager/logs/`
  (falling back to `~/.local/state` when unset), not
  to a pipe the manager holds. A reader thread tails that file
  into the project's `LogBuffer` via a queued Qt signal. Merging
  keeps the ordering the user would have seen in a terminal.
  **A file rather than a pipe is deliberate:** a child inheriting
  a pipe dies of `SIGPIPE` the moment it writes after the manager
  has exited, which would make "children are left running" below
  false in practice and break re-adoption. A file has no reader
  to lose. It also means a **re-adopted** server (started before
  this manager, or before this manager run) still has a readable
  log if it was started by *a* manager — and honestly has none if
  it was started from a terminal, which the UI states rather than
  showing an empty panel.
- **Stop** sends `SIGTERM` to the group, waits a grace period
  (default 5 s), then sends `SIGKILL` **while our child is still
  unreaped**. Stop runs on a **worker thread** — a 5-second wait on
  the UI thread would freeze the window. **Restart** is stop
  followed by start, with the same pre-flight port check.

  **Never signal a bare integer** (security review, 2026-08-03). An
  earlier version escalated when "anything is alive **or** the port
  is still bound", and that `or` fires precisely when our child is
  already gone and something *else* holds the port — the everyday
  `running (wrong port)` case. `Popen.poll()` has reaped the PID by
  then, so `os.killpg(child.pid, …)` targets a number the kernel is
  free to have reissued, and a recycled PID that happens to lead a
  group takes out an unrelated one.

  Two rules follow. Signal through **`psutil.Process` handles**
  (`terminate()` / `kill()`), which raise `NoSuchProcess` on PID
  reuse — verified in psutil 7.2.2 that `_send_signal` calls
  `_raise_if_pid_reused()`, which `os.kill` and `os.killpg` cannot.
  And **do not reap the managed child until the stop sequence
  ends**, so its PID cannot be recycled while still in use as a
  process-group id. "The port is still bound" is a reason to *warn*,
  never a reason to signal.
- On manager exit (the deliberate Quit, not window-close),
  children are **left running** by design — servers outlive the
  window, and ADR-0004 lets a later session re-adopt them. This
  is only true because of the log-file redirection above.

### Service-managed projects are the exception

**Amended 2026-08-03, before implementation, per ADR-0001's
review-gate carve-out.** Not every project is started by running
a script. `project-a` is driven by an **enabled
systemd user unit**, `project-a.service` — verified via
`systemctl --user list-unit-files`, and its own tray applet
drives it with `systemctl --user is-active / stop / restart`.

Spawning `node serve.mjs` directly for that project would be
actively wrong: systemd already has an instance on port 4321, so
the manager would either collide with it or create a second,
unsupervised copy that systemd knows nothing about. The port
probe would then report a state neither party controls.

So the Scanner recognises a **`systemd` launcher kind**, and for
those projects every verb goes through the service manager
instead of `subprocess`:

| Verb | Process-managed | Service-managed |
|---|---|---|
| start | `Popen(start_new_session=True)` | `systemctl --user start <unit>` |
| stop | `SIGTERM` → `SIGKILL` to the group | `systemctl --user stop <unit>` |
| restart | stop then start | `systemctl --user restart <unit>` |
| liveness | our child's PID | `systemctl --user is-active <unit>` |
| logs | our per-project log file | `journalctl --user -u <unit> -f` |

Port probing is unchanged — ADR-0004 classifies from the socket
table either way, which is precisely the benefit of deriving
state from observation rather than from ownership. A
service-managed project is never `running (foreign)` merely
because this manager did not spawn it; the launcher kind tells
the classifier that systemd's instance *is* the managed one.

**Detection:** a project is service-managed when a
`systemctl --user` unit exists whose name matches the project, or
when the registry records a unit name for it. Because unit naming
is a convention rather than a rule, a wrong guess here is
correctable in the UI like any other detected field (ADR-0005).

**Delivering a port to a service-managed project needs a drop-in,
not an environment variable.** systemd does not inherit the
caller's environment, so `PORT=5999 systemctl --user start <unit>`
starts the service with no `PORT` at all and the reassignment
silently does nothing — the exact failure ADR-0002 exists to
prevent, arriving through a channel that ADR's author did not
consider. Verified 2026-08-03 against a real unit, which sets its
port with `Environment=` in the unit file itself.

So for a service-managed project the manager writes a **drop-in it
owns**:

```
~/.config/systemd/user/<unit>.d/50-lwsm-port.conf
[Service]
Environment=PORT=<effective port>
```

then `systemctl --user daemon-reload` before starting. Notes that
make this safe rather than clever:

- **It is not a write into a sibling project.** The drop-in lives
  in the *user's* systemd configuration, so
  `docs/standards/coding.md § O3` still holds — the project
  directory remains read-only to this app. It is, however, a third
  kind of write beyond the two config files in § Persistence, and
  is named here for that reason.
- **The filename is owned and namespaced** (`50-lwsm-port.conf`),
  so the manager can remove exactly its own override and never
  touch a drop-in someone else wrote.
- **A drop-in `Environment=` adds a variable rather than replacing
  the unit's list**, which is what makes this compose: a unit that
  already sets its own port variable keeps it as the default, and
  a compliant server prefers `PORT` over it by the precedence in
  ADR-0002 case 5. Nothing in the project's own unit needs editing.
- **Removing the override removes the file** and reloads, rather
  than writing the old value back — so the project returns to
  exactly its packaged default rather than to whatever the manager
  believed the default was.

**A companion process must read the *unit's* environment, not its
own.** Verified during adoption on 2026-08-03: a service-managed
project's tray applet derived its URL from `STATS_PORT` in its own
environment, which is not where the service's port comes from —
systemd supplies that from the unit plus any drop-in. The applet
would have kept opening the old port, and POSTing to it, while the
server was perfectly healthy somewhere else: confidently wrong,
with nothing broken to notice.

The general rule for service-managed projects is that **the unit
is the source of truth for the runtime environment**, so anything
that needs to know the port asks
`systemctl --user show <unit> -p Environment` rather than reading
its own. That project's fix was verified adversarially — a forged
`PORT` planted in the applet's own environment did not move it —
which is the right shape of test, because reading the correct
value and ignoring the wrong one are two different properties.

**A unit name is untrusted input** (security review, 2026-08-03):

- **Validate it** against `^[A-Za-z0-9@:_.\-]{1,255}\.(service|socket|target|timer)$`,
  reject a leading `-`, and pass `--` before it. A name beginning
  with `-` is consumed by `systemctl` as an *option* — `--host=`,
  `-M`, `--machine=` all redirect which manager is driven. The
  project's own `coding.md § 7` already mandates the `--`
  separator; it simply was not carried into this table.
- **Bind by `FragmentPath`, not by directory name.** Matching on
  the project's directory name means `mkdir <scan root>/project-a`
  — an empty directory with no code in it — is enough to make the
  UI present a row whose Start and Stop drive somebody else's
  service. The unit is bound to a row only when its `FragmentPath`
  or `WorkingDirectory` resolves inside that project directory.

## Consequences

**Positive:**

- Stopping a project stops the whole tree, so ports are actually
  released — the single most important correctness property of
  the Stop button.
- Service-managed projects are driven by the thing that already
  owns them, rather than fought with.
- No sibling project has to change to be launchable, which was
  the point of using their own scripts.
- `shell=False` plus an argument vector removes shell-injection
  and quoting bugs from paths like `<scan root>/…`.

**Negative:**

- The Qt-native convenience of `QProcess` (`readyReadStandardOutput`,
  `finished`) is replaced by a reader thread per running server
  and explicit reaping. That is real code the project now owns
  and must test.
- Thread-to-UI handoff must be queued signals; a direct widget
  touch from the reader thread would be a crash. This is a
  standing review item for any code in `Supervisor`.

**Neutral:**

- Unix-only, via `os.killpg` and session semantics. The project
  is openSUSE/KDE-targeted and cross-platform support is out of
  scope, so this costs nothing today. Should that change, the
  process-group logic is the port surface, isolated in
  `Supervisor`.
