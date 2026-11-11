# ADR-0008: How updates reach users — the AppImage updates itself

- **Status:** Accepted
- **Date:** 2026-11-11
- **Deciders:** Project lead
- **Roadmap:** LWSM-1043
- **Related:** [ADR-0003](0003-launch-via-project-scripts.md)

## Context

Since 0.5.1 a release is one AppImage, attached to the GitHub release. Nothing
tells a user that a newer one exists.

LWSM-1043 asked first whether this app should register with **OneUp**, the
author's update dashboard, rather than grow an updater of its own. OneUp was
read on 2026-11-11 (its `README.md`, `oneup/engine/__main__.py`,
`oneup/gui/self_update.py`). It cannot take this app:

- **It updates a fixed set of things**: openSUSE's system packages, Flatpaks,
  firmware, leftover packages and the package cache. `ALL_STEPS` in
  `oneup/engine/__main__.py` lists them. Nothing lets another app register.
- **It runs on openSUSE only.** Its README says it is not packaged for other
  distributions. This app's AppImage is meant for any current x86-64 Linux.
- **Its self-update updates OneUp alone.** `self_update.ASSET` names OneUp's
  own AppImage.

Making OneUp update other AppImages would change what OneUp is for. That is a
decision for OneUp, not this project.

Two sibling projects have already built an AppImage that updates itself, on
the same stack (PySide6, frozen by PyInstaller): finbreak (FIBR-0054), and
OneUp after it (`docs/specs/ONEUP-0112-self-update.md` in OneUp). The OneUp
spec records the bugs finbreak shipped and fixed. LWSM-1043's roadmap bullet
summarises finbreak's.

## Decision

**The AppImage updates itself, on the model of OneUp's ONEUP-0112.** The user
chose this on 2026-11-11 over two cheaper options: a notice that links to the
download page, and no check at all.

The shape, to be specified by the item that builds it:

- **It checks GitHub's releases list for this repository.** It does not use
  OneUp or any tool on the user's machine.
- **It updates only a running AppImage.** A checkout or `uv run` gets no update
  offer; git and uv own those.
- **Nothing downloads without a click.** The user presses an update button
  first.
- **Every download is verified before it runs.** An Ed25519 signature is
  checked against a public key built into the app. The private key stays on
  the author's PC, as OneUp's does. A GitHub secret would let anyone who got
  into the account sign a fake update.
- **The verified bytes are the bytes installed.** The download is held in
  memory, verified, then written over the AppImage. This closes the gap that
  finbreak's FIBR-0170 fixed.
- **The relaunch is a detached shell that waits for the old process to exit**,
  with the loader variables restored. finbreak needed three attempts to get
  this right.

## Consequences

- **The release process gains a signing step on this PC.** CI builds and
  attaches the AppImage. `scripts/sign-release.py publish` then signs it and
  uploads the signature, after the release is published;
  `scripts/local-release.sh` only checks beforehand that the key is present.
  A release without a signature is never offered as an update.
- **A relaunch fix reaches users one release late.** The version doing the
  relaunch is the old one. finbreak had to tell users this three times.
- **Running servers are not interrupted.** Servers outlive the manager
  (ADR-0003), and the relaunched app finds them again by probing (ADR-0004).
- **The app must save the AppImage's path before scrubbing its environment.**
  `_forget_bundle_environment` in `src/lwsm/__main__.py` deletes `APPIMAGE` at
  start-up. The update needs that path.
- **The app makes its first requests to the internet.** The check runs at
  every start by default, with an off switch in Settings (LWSM-1548).

## Alternatives considered

- **Register with OneUp** — not possible without changing OneUp (§ Context).
- **A notice linking to the release page** — much less to build, and no signing
  key. Rejected by the user on 2026-11-11.
- **No update check** — nothing to build. Rejected by the user on 2026-11-11.
- **AppImageUpdate with zsync** — OneUp rejected it in ONEUP-0112 because it
  needs `gpg` and another tool on the user's machine.
