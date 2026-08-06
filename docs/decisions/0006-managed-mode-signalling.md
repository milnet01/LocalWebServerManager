# ADR-0006: Managed-mode signalling — `LWSM_MANAGED`

- **Status:** Accepted
- **Date:** 2026-08-03
- **Deciders:** Project lead
- **Related:** [ADR-0002](0002-port-contract.md),
  [ADR-0003](0003-launch-via-project-scripts.md),
  `docs/private/port-contract-prompt.md` (author-private)

## Context

Two sibling projects ship their own system-tray applet whose job
is to start their server at login and offer start / stop / open.
Once this manager does that centrally, those applets are
redundant — two tray icons for what is now one row in one window.

The user asked for the siblings to **detect this manager and
suppress their own tray**. "Detect" admits two very different
readings, and picking the wrong one produces a bad failure:

1. **Is the manager installed on this machine?** — the literal
   reading. But a user who starts `project-c` by hand from a
   terminal, with the manager closed, then has no tray *and* no
   manager: the app becomes harder to reach than before. The
   condition is also awkward to test without coupling every
   sibling to this project's install paths.
2. **Did the manager launch this instance?** — narrower, and
   exactly the condition under which a tray is redundant. It is
   also trivially testable and creates no coupling at all.

Reading 2 is strictly better: it suppresses the tray in every
case the user cares about, and keeps it in the one case where
losing it would hurt.

A third option — the manager writes a marker file that siblings
look for — was rejected. It inverts the dependency (siblings
would read this project's config directory), and it cannot
distinguish "installed" from "running" from "launched this
instance" without more machinery than the problem deserves.

## Decision

**The manager sets `LWSM_MANAGED=1` in the environment of every
process it spawns. A sibling that sees it suppresses its own tray
icon and runs headless.**

The contract, for the sibling side:

1. If `LWSM_MANAGED` is set to `1`, do not create a tray icon.
   Run the server exactly as normal, logging to stdout.
2. If it is absent or set to anything else, behave exactly as
   today — tray and all. Absence must be the unchanged path, the
   same rule as ADR-0002 case 3.
3. Do not condition anything **but** the tray on it. It is not a
   licence to change ports, paths, or logging; the manager reads
   stdout and probes ports, and both must work identically either
   way.

**`LWSM_MANAGED` is a presentation hint with no security value.
Never use it to grant, skip, or relax anything.** It is
unauthenticated, trivially forged (`LWSM_MANAGED=1 ./start.sh`),
inherited by every descendant, and readable from
`/proc/<pid>/environ` by any local process. Stated here in the
normative voice, and repeated in the adoption prompt, because this
text is pasted into seven separate codebases where the natural next
thought is *"if we're managed, we can skip the confirmation"* or
*"…enable the debug endpoint"*. That sentence costs nothing today
and is impossible to retrofit across seven repositories later
(security review, 2026-08-03).

It travels with `PORT` in the same environment, is delivered by
the same adoption prompt, and is one `os.environ.get` on the
sibling side.

**Quitting the tray must not become quitting the server.** One
sibling tray's Quit stops its server, and another's is labelled
"Quit (stops the server)". A suppressed
tray means neither runs — which is correct — but any sibling
retaining a headless quit path must not stop a server the manager
believes it owns.

## Consequences

**Positive:**

- The two per-project tray applets can be deleted from
  `~/.config/autostart/` once the manager's own start-at-login
  lands (LWSM-1027), which is what makes the consolidation a real
  simplification rather than a trade.
- No coupling: a sibling never learns this project's name, paths
  or config format. It reads one environment variable.
- A hand-launched server keeps its tray, so nothing is lost in
  the case where the manager is not involved.
- Costs the sibling one line, and adoption is independent per
  project.

**Negative:**

- Does not satisfy the literal request. A user who launches a
  sibling by hand *while the manager is open* still gets a tray
  icon alongside the manager's row. Judged the right trade: a
  spurious tray is a cosmetic annoyance, a missing one is a
  usability loss.
- One more thing for each sibling to implement, though it rides
  along with the port contract they are already adopting.

**Neutral:**

- Nothing enforces it. A sibling that ignores `LWSM_MANAGED`
  shows a redundant tray and is otherwise fine — the same
  gradual-adoption posture as the port contract.
