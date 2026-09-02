# ADR-0005: A persisted registry whose rescan never discards user edits

- **Status:** Accepted
- **Date:** 2026-08-03
- **Deciders:** Project lead
- **Related:** [ADR-0002](0002-port-contract.md),
  [ADR-0004](0004-runtime-truth-from-probing.md),
  [docs/discovery.md](../discovery.md)

## Context

The user chose auto-scan with persistence plus an explicit
**Rescan** button (2026-08-03). That combination only works if
the merge rules are pinned down: a scan produces facts about
disk, the stored registry holds the user's intent, and the two
will disagree — a project gets renamed, a launcher changes, a
port override exists that contradicts the port detected in
source.

Pure auto-scan every launch was rejected in discovery because it
cannot hold an override. A hand-maintained list was rejected
because it means seven entries of typing and manual upkeep
forever. So the registry has to reconcile.

Projects also come and go in `<scan root>/` — the
seven found today are a snapshot, not a fixed set.

## Decision

**The registry stores user intent; a scan refreshes only
detected facts; on conflict, user intent wins and the
disagreement is reported.**

- **Identity is the project's absolute path.** Renaming the
  *display name* keeps identity; moving the directory is a
  remove plus an add, which the merge reports rather than
  silently reconciling.
- **Each record has two halves.** *Detected* — launcher command,
  declared port, runtime kind, systemd unit name — refreshed on
  every scan. *User-owned* — display name, hidden flag, port
  override, launcher override, notes, start-at-login flag, and
  the **`actions` list** (`docs/design.md § Custom project
  actions`) — never written by a scan.

  The `actions` list is user-owned by design and not merely by
  convention: a scan that discovered commands inside a project
  and offered to run them would be a different and far riskier
  product than a scan that reports how a project starts.
- **Merge outcomes**, reported after every rescan so the button
  produces a visible answer rather than a silent mutation:
  - **New:** on disk, not in the registry → added, flagged *new*.
  - **Unchanged:** detected fields match → nothing to say.
  - **Changed:** detected fields differ (a launcher was renamed,
    a hard-coded port moved) → detected half updated, the change
    listed. If a user override exists for the field that moved,
    the override stays in force and the row is flagged
    *override differs from detected*, so a stale override is
    visible instead of mysterious.
  - **Missing:** in the registry, absent from disk → marked
    *missing*, kept, never auto-deleted. Removal is a user
    action, because an unmounted drive must not destroy the list.
- **Duplicate ports are flagged at merge time**, not at launch
  time, naming both projects. ADR-0004 cannot distinguish two
  projects sharing a port by probing, so the registry is where
  that ambiguity is caught. **The tie-break is explicit:** the
  port belongs to the project whose record was registered first
  (earliest `added` timestamp); every later claimant is marked
  *port claimed by `<other project>`* and its Start is refused
  with that message until the user re-ports one of them. No
  silent winner, and no state where two rows both claim to own
  one port.
- **Effective port** = port override if set, else declared port.
  This is the value the pre-flight check tests and the value
  passed as `PORT` (ADR-0002). **An override is validated at
  entry** against the same 1024–65535 range ADR-0002 requires,
  and rejected in the UI with that reason. Otherwise an override
  of 80 would be accepted here and turn into an unexplained
  launcher crash later, which is precisely the silent-failure
  shape ADR-0002 rule 4 exists to prevent.
- **Hidden projects are not polled.** Hiding a project removes it
  from the list and from the status loop; it keeps its record and
  its overrides, and un-hiding restores both.
- Writes are atomic (temp file, `fsync`, `os.replace`) and the
  file carries a `schema_version`; an unrecognised version is
  refused with a clear message rather than partially parsed.

## Consequences

**Positive:**

- The user can rename, hide, and re-port projects, and a Rescan
  will not undo it — which is the whole reason the list is
  persisted.
- New sibling projects are one button away from being managed,
  with no editing.
- Detection being advisory rather than authoritative means a
  wrong guess by the Scanner is correctable in the UI instead of
  being a bug report.

**Negative:**

- A stale override can persist indefinitely — the user set a port
  override, the project later changed its own default, and the
  override still wins. The *override differs from detected* flag
  makes that visible **on the rescan where the detected port
  moves**, which is the rescan that creates the staleness — not
  on every rescan afterwards. So the mitigation is a single
  announcement, and a user who misses it is not told again. A
  real class of confusion the design accepts.

  Stated this way from 2026-09-02: this paragraph said "visible
  on every rescan", which the merge has never done and neither
  the outcome list above nor `LWSM-1131 § 4.3`'s table ever
  claimed — both say the flag fires when the field that moved
  has an override. The text was the wrong side.
- Records for deleted projects accumulate as *missing* until the
  user clears them.

**Neutral:**

- JSON, not a database. At the scale of tens of projects, the
  merge is a dictionary walk and the file is human-readable and
  hand-fixable, which is worth more here than query capability.
