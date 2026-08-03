# ADR-0002: The `PORT` contract

- **Status:** Accepted
- **Date:** 2026-08-03
- **Deciders:** Project lead
- **Related:** [ADR-0003](0003-launch-via-project-scripts.md),
  [ADR-0004](0004-runtime-truth-from-probing.md),
  [ADR-0005](0005-registry-and-rescan.md) (defines *effective
  port*, the value this ADR's pre-flight tests),
  [docs/discovery.md](../discovery.md)

## Context

Two agreed requirements pull against each other. The manager
**runs each sibling project's own launcher** (`start.sh`,
`serve.py`, `npm run dev`), and the user wants to **reassign a
project's port** from the manager. But several launchers hard-code
their port — `project-f/app.py:888` passes `port=5005`
literally — so the manager cannot change a port it does not
control.

Three ways out were considered:

1. **Rewrite the launcher from the manager.** Rejected — editing
   sibling projects is explicitly out of scope
   (`docs/discovery.md § Out of scope`), and a manager that
   rewrites the thing it manages is a source of surprise.
2. **Accept hard-coded ports; drop reassignment.** Rejected — the
   user asked for reassignment, and port clashes are one of the
   pains the project exists to remove.
3. **Define a contract the projects adopt.** Chosen. The user
   will run the change in each sibling's own Claude Code session
   (decision, 2026-08-03), so the manager's job is to specify the
   interface precisely and behave correctly for projects that
   have not adopted it yet.

The variable name was chosen between `PORT`, `LWSM_PORT`, and
both-with-precedence. `PORT` won: it is the near-universal
convention (Flask, Vite, Node hosting platforms all read it), so
some siblings need a one-line change or none at all. The cost is
a small chance of collision with an unrelated `PORT` in the
environment — acceptable, because the manager always sets it
explicitly per child process rather than relying on an inherited
value.

## Decision

**A compliant launcher reads the `PORT` environment variable and
binds that port.**

The per-project adoption prompt generated from this ADR lives at
`docs/private/port-contract-prompt.md`, which is author-private
because it names real files in real projects (LWSM-1045). This
ADR is canonical; if the two disagree, the prompt is the bug.

The contract, in full:

1. On startup the launcher reads `PORT` from its environment.
2. **`PORT` present and valid** — parses as an integer in
   **1024–65535**: the server binds that port.
3. **`PORT` absent** (unset, or set to the empty string): the
   launcher falls back to **its existing behaviour, unchanged** —
   which for four of the seven known projects is not a hard-coded
   literal but their own port variable or saved setting. Running
   the project standalone must behave exactly as it does today;
   adoption may not break `./start.sh`.
4. **`PORT` present but invalid** — non-numeric, or an integer
   outside 1024–65535: a **startup error**, not a silent
   fallback. The launcher exits non-zero with a message naming
   the bad value. Silently ignoring a requested port is the
   failure mode this whole ADR exists to prevent.

5. **Precedence, where the project already has its own port
   variable or saved setting** — and four of the seven do
   (`PROJECT_A_PORT`, `PROJECT_B_PORT`, `PROJECT_E_PORT`, and
   project-d's saved `server_port`): **`PORT` wins**, then the
   project's own mechanism, then its hard-coded default. The
   project's own variable keeps working exactly as before
   whenever `PORT` is absent. One predictable knob for the
   manager; nothing taken away from the project.
6. **Recommended, not required:** on successful bind, print the
   bound URL to stdout — e.g. `Listening on http://127.0.0.1:5005`.
   The manager does not depend on this (it probes the socket
   table instead, per ADR-0004), but it makes the log panel
   immediately useful.

**Cases 2, 3 and 4 are exhaustive and mutually exclusive** over
the value of `PORT`: case 3 is absence alone, never a malformed
value. Case 5 governs what "its existing behaviour" in case 3
resolves to.

The manager's obligations are the other half of the contract:

- **Pre-flight.** Before spawning, the manager checks that the
  effective port is free. If it is held, the launch is refused
  and the holder is named — or reported as another user's process
  when the PID cannot be resolved. The manager never launches a
  project into a port it already knows is taken.
- **Post-flight.** After spawn, the manager verifies which port
  the child actually bound, by asking `PortProbe` **which ports
  the child's process group holds** — the reverse of the
  pre-flight question, and a distinct capability that
  `docs/design.md § Components` names explicitly. If the bound
  port differs from the requested one, the project enters the
  `running (wrong port)` state defined in
  [ADR-0004](0004-runtime-truth-from-probing.md): shown as
  running, on the port it really bound, flagged as **not
  honouring the port contract**. A reassignment that did not take
  effect is never displayed as though it had — and a project that
  binds *something* is never reported as `failed`, which is the
  expected everyday outcome for a sibling that has not adopted
  the contract yet.

## Consequences

**Positive:**

- One interface, specified once, that every sibling implements
  identically — the per-project prompt is generated from this ADR
  rather than improvised seven times.
- Projects that already read `PORT` work with no change at all.
- Adoption is incremental and safe: a non-adopting project keeps
  working, and its status tells the truth about why its port did
  not change.
- Rule 4 makes a misconfigured port loud and immediate rather
  than a confusing "why is it on the old port" hunt later.

**Negative:**

- Seven sibling projects need a change, coordinated by the user
  across separate sessions; until each lands, that project's port
  is effectively fixed.
- `PORT` is a common name. A launcher that inherits a stray
  `PORT` from a user's shell will now honour it. Mitigated by the
  manager always setting the variable explicitly for children it
  spawns, so behaviour under the manager is deterministic.

**Neutral:**

- The contract says nothing about the bind address; projects keep
  whatever they use today (`127.0.0.1` or `0.0.0.0`). Network
  exposure is out of scope for this project.
