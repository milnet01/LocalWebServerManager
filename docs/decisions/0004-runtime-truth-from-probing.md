# ADR-0004: Derive running state by probing, not by remembering

- **Status:** Accepted
- **Date:** 2026-08-03
- **Deciders:** Project lead
- **Related:** [ADR-0002](0002-port-contract.md),
  [ADR-0003](0003-launch-via-project-scripts.md),
  [docs/discovery.md](../discovery.md)

## Context

`docs/discovery.md § Success criteria` #3 requires status to stay
truthful in three awkward cases: a server started from a terminal
must show as running; a server the manager started and someone
killed externally must show as stopped; and closing and reopening
the manager must neither lose nor invent state.

A manager that trusts its own memory — "I started it, therefore
it is running" — fails all three. A PID file fails differently:
PIDs are reused, and a stale file confidently names an unrelated
process.

The observable fact that actually matters to the user is
narrower and more durable than either: **is something listening
on that port right now, and what is it?**

The user also chose (2026-08-03) that a server the manager did
not start should be visible **and** stoppable, with a
confirmation step first.

## Decision

**The live TCP socket table is the source of truth for whether a
project is running. The manager's own bookkeeping only refines
that answer.**

Each poll takes **one** socket-table snapshot and classifies
every project against it. Classification combines what the
`Supervisor` knows about a child it owns with two questions
`PortProbe` answers from that snapshot: *what holds the effective
port?* and *which ports does this process group hold?* The second
is what makes the post-flight check in ADR-0002 implementable.

**Seven derived states** — `stopped`, `starting`,
`running (managed)`, `running (wrong port)`, `running (foreign)`,
`port blocked`, `failed`. The list is exhaustive for states
*derived from observation*, and the UI renders each distinctly.
`stopping` is **not** among them: it is a transient overlay label
the controller applies while a stop is in flight
(`docs/design.md § State management`), never a conclusion drawn
from the socket table. The distinction matters because
`docs/standards/testing.md § T7` requires one test case per
derived state, and an overlay label has nothing to derive.

| Own child | Effective port held by | Child holds any port | State |
|---|---|---|---|
| live | that child's group | — | `running (managed)` |
| live | anyone else, or nobody | yes, a different port | `running (wrong port)` — bound, but not where asked (ADR-0002) |
| live | nobody | no | `starting` — no deadline; see § Slowness is not failure |
| live | a process that looks like this project | no | `running (foreign)` — the user also started it by hand |
| live | any other process | no | `failed` (port taken after pre-flight) |
| just exited, stop **was** requested | — | — | `stopped` |
| just exited, stop was **not** requested | — | — | `failed` (exited on its own) |
| none | a process that looks like this project | — | `running (foreign)` |
| none | any other process | — | `port blocked` |
| none | nobody | — | `stopped` |

Three rules the table depends on:

- **"Looks like this project"** is a plausibility test: the
  holder's executable path or working directory lies under the
  project directory. Without it, any unrelated process on port 5000
  would make project-d read as running, and the pre-flight warning
  that discovery success criterion 4 requires could never fire. A
  holder that fails the test — or whose PID cannot be resolved at
  all — is `port blocked`: the project is not running, something is
  in its way, and Start is refused with that explanation.

  **It is a display heuristic with no security value, and nothing
  may be gated on it** (security review, 2026-08-03). `chdir()` is
  free: any local process can `cd` into a project directory and
  bind its port, and the manager will then label it
  `running (foreign)`, show an uptime for it, and — as originally
  designed — enable **Open in browser**. That is localhost phishing
  with this app's credibility behind it. So Open-in-browser on a
  `running (foreign)` row carries the same disclosure the Stop path
  does: the holder's executable path, uid, cmdline and start time,
  shown before anything opens. For a *managed* server, identity is
  the recorded child PID **plus its `create_time`**, never the
  working directory.
- **An exited child is remembered for exactly one classification**,
  and which of `stopped` / `failed` it produces is decided by
  **whether the app asked it to stop** — that flag is the only
  thing separating a clean shutdown from a crash, since both look
  identical from the socket table. After that one poll the record
  is discarded and the project is classified from the socket
  table alone. Otherwise a once-failed project would read
  `failed` forever, including after the user starts it from a
  terminal. The UI keeps showing the last failure's log tail
  after the state clears; the *log* is history, the *state* is
  not.
- **A project's `declared` port is probed as well as its
  effective one, whenever the two differ.** Without this, the
  whole `running (wrong port)` case evaporates the moment the app
  restarts: a non-adopting project asked for 5999 is still
  sitting on its hard-coded 5005, nothing holds 5999, and the
  table would say `stopped` — then Start would cheerfully spawn a
  duplicate. Probing both ports means a restarted manager
  re-adopts it as `running (foreign)` on the port it really
  holds, which is the truth. This costs nothing extra: both ports
  are read from the same snapshot.

### Slowness is not failure — amended 2026-08-03

The original rule gave `starting` a **15-second** deadline, after
which a child that had bound nothing was called `failed`. That is
wrong, and adoption work found it by accident: a managed project
parses a large data file before it binds and **takes about 40
seconds**, so the manager would have reported a perfectly healthy
launch as a failure and shown the user a lie — the precise defect
this whole ADR exists to prevent, reintroduced by a constant.

That is no longer a single lucky catch: the adoption campaign
finished with **two independently measured projects** past the old
deadline — ~40 s and ~45 s to bind — the second found because a
fixed `sleep` in the verification prompt produced a false negative
on it (2026-08-06).

No deadline can be right here. Bind time depends on the project's
own work, ranges over an order of magnitude between a static
server and a cold `npm run dev`, and is not knowable in advance.
A number chosen by the manager is a guess about someone else's
program.

So the rule is now:

- **While our child is alive and has bound nothing, the project is
  `starting` — with no deadline**, and the UI shows the elapsed
  time. That is the honest description: it *is* starting, and it
  has not failed at anything.
- **`failed` requires evidence, not a timer**: the child exited
  without ever binding, or exited non-zero. An exit is a fact; a
  stopwatch is an opinion.
- A **soft threshold** (default 30 s, settings-backed) changes the
  *label* to `starting (slow — 42s)`. It informs; it never
  reclassifies. A genuinely hung server sits visibly in
  `starting` with a rising counter, which is both true and
  obvious, rather than being mislabelled `failed` at an arbitrary
  moment.
- **Bind time is learned, exactly as the port is** (LWSM-1038).
  Once a project has been observed binding in ~40 s, the app knows
  that and can say "usually ready in about 40 seconds" instead of
  implying something is wrong. The same principle as
  `confirmed_port`: observe the project rather than assume it.

The log panel streams throughout, so the user is never staring at
a bare spinner — the slow project's own output is the progress
indicator, and it is more informative than any state name.

Consequences of the rule:

- **Nothing about runtime state is persisted.** On startup the
  manager knows only the registry (paths, ports, user overrides)
  and derives everything else by probing. A relaunch of the
  manager therefore re-adopts servers correctly by construction,
  including ones started before it existed.
- **Foreign servers are shown, labelled, and guarded.** A
  `running (foreign)` project displays as running with a marker
  that it was started outside the app. Stop is enabled but asks
  for confirmation first, because the app is signalling something
  it did not create.
- **Stopping a foreign server signals a tree, not a group.**
  ADR-0003's `os.killpg(child.pid, …)` is safe only because
  `start_new_session=True` made that child its own group leader.
  A foreign PID is usually **not** a group leader — its group is
  the terminal job that launched it, which may hold the user's
  shell and unrelated commands. So the foreign path instead
  resolves the holder PID, enumerates its **descendants** via
  `psutil.Process.children(recursive=True)`, names the whole set
  in the confirmation dialog, and signals exactly that set —
  through the retained `Process` objects, per ADR-0003, so a PID
  recycled meanwhile raises instead of killing a stranger.

  **The set is re-enumerated after the user confirms, not before.**
  A modal dialog waits an unbounded time; processes die, PIDs get
  reused, and children spawned during the wait are missed. If the
  set changed while the dialog was open, the user is asked again
  rather than shown a stale list. And because a process chooses its
  own name, the dialog renders **pid / executable path /
  create-time as separate columns** — never one formatted sentence
  a hostile process can shape into "only one harmless thing will
  die". This dialog is the only guard on signalling something the
  app did not create, so it has to be unspoofable.
- **An unattributable holder is reported, not guessed.** `psutil`
  resolves an owning PID only for processes the current user can
  see — measured on this machine 2026-08-03: 5 of 11 listening
  sockets were attributable and 6 were not. When the PID is
  unavailable the port shows as held by a process this user
  cannot inspect, the project reads `port blocked`, Stop is
  disabled, and no name is invented.

## Consequences

**Positive:**

- All three awkward cases in success criterion 3 are satisfied by
  the same mechanism rather than by three special cases.
- No PID files, no lock files, no stale-state recovery code, and
  nothing to clean up after a crash of the manager itself.
- A crash of the manager cannot orphan state, because there was
  no state to orphan.

**Negative:**

- A poll costs **one** socket-table read per tick, not one per
  project. It runs off the UI thread; the interval is
  settings-backed.
- **The default interval is 1 second**, not 2. Discovery success
  criterion 2 asks for a transition to be visible within 2
  seconds, and worst-case latency is one full interval plus probe
  time — at a 2 s interval that exceeds the budget it was meant
  to satisfy. At 1 s it fits with room to spare, and a socket-table
  read is cheap enough that the doubled rate is not worth
  optimising.
- Actions the user takes in the app apply an **optimistic
  overlay** so buttons feel immediate: pressing Start shows
  `starting` at once rather than waiting for the next poll. The
  overlay is a labelled, expiring layer over the derived state —
  its rules are in `docs/design.md § State management`, and it
  never becomes a second store.
- Two projects deliberately sharing a port cannot be told apart
  by probing alone. The registry treats a port as belonging to
  one project and flags duplicates at merge time (ADR-0005).

**Neutral:**

- Only TCP listeners are probed. A project serving over a unix
  socket would be invisible; none of the seven surveyed projects
  does, and this is recorded as a known limitation rather than
  designed around.
