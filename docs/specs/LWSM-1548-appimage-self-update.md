<!-- ants-spec-format: 1 -->
# LWSM-1548 — The AppImage updates itself, from a signed release

**Status:** accepted (2026-11-11).
**Kind:** feature.
**Source:** ROADMAP LWSM-1548 (ADR-0008, user-2026-11-11).
**Pairs with:** [ADR-0008](../decisions/0008-updates-reach-users.md), which
decided the shape; this spec is its contract.

**Layman:** When a newer version is released, the downloaded app says so, shows what
changed, and on one click replaces itself with a copy it has proved came from
the author, then reopens.

## 1. Goal

After this ships, a running AppImage asks GitHub at start-up whether a newer
release exists. When one does, a banner above the project list offers it. The
banner opens a window holding every newer version's release notes. **Update
now** downloads the new AppImage into memory, checks its Ed25519 signature
against a public key built into the app, writes it over the running file, and
reopens the app. A copy run from source is never offered an update.

## 2. Problem

1. **Nothing tells a user that a newer version exists.** Since 0.5.1 a release
   is one AppImage attached to the GitHub release, and the app has no network
   code beyond its own health checks: `lwsm.health` talks to `localhost` only,
   through `http.client.HTTPConnection`.
2. **The app forgets it is an AppImage.**
   `lwsm.__main__._forget_bundle_environment` deletes `APPIMAGE` (one of
   `_APPIMAGE_VARIABLES`) at start-up, so every program the app starts gets
   the launch environment. The update needs that path, so it must be read
   before the scrub.
3. **A swap has to defeat the single-instance guard.**
   `lwsm.__main__.claim_single_instance` hands a second launch to the running
   copy and exits it. A new copy started before the old one has gone would be
   handed back to the old one and close.
4. **No release is signed.** `.github/workflows/release.yml` builds the
   AppImage and attaches `LocalWebServerManager-<version>-x86_64.AppImage`
   with `gh release upload`; nothing signs it. `gh release view v0.5.1 --json
   assets -q '.assets[].name'` on 2026-11-11 →
   `LocalWebServerManager-0.5.1-x86_64.AppImage`, alone.

**The reference design is OneUp's ONEUP-0112**, built 2026-11-08 on the same
stack (PySide6, frozen by PyInstaller, Qt's network classes). It carries
finbreak's lessons, which LWSM-1043's roadmap bullet also summarises. This
spec takes its shape and states where this app differs:

- **This app is frozen `--onedir`, not `--onefile`**
  (`scripts/_appimage-build.sh`'s `pyinstaller --onedir`), and the AppImage's
  `AppRun` `exec`s the frozen `lwsm` (read from the 0.5.0 AppImage's
  `AppRun`, 2026-11-11). So no bootloader parent process outlives the app, and
  the relaunch waits for this process alone (§4.7).
- **The launch environment is already clean.** `lwsm.__main__.run` calls
  `_restore_launch_library_path` before `main`, and `main` calls
  `_forget_bundle_environment`. Every child, the relaunch included, inherits
  that cleaned `os.environ`.
- **There is no package install.** The app ships as an AppImage or runs from a
  checkout, so there are two install kinds, not three.
- **The bundle can already speak HTTPS.** The 0.5.0 AppImage, extracted on
  2026-11-11, holds `PySide6/Qt/plugins/tls/libqopensslbackend.so`,
  `libssl.so.3` and `libcrypto.so.3`. Qt's backend reads the host's own CA
  store, which Python's `ssl` in the bundle would not find on every
  distribution.

## 3. Scope decisions (agreed with the user)

Decided by the user on 2026-11-11 unless marked otherwise.

1. **The AppImage updates itself** — download, verify, swap, relaunch (ADR-0008).
2. **The check runs at every start, on by default**, with an off switch in
   Settings. Only a running AppImage checks.
3. **`cryptography` becomes a runtime dependency.** It verifies the signature.
   The "two, and no more than two" comment in `pyproject.toml` is rewritten to
   say why there are three.
4. **An update rewrites the same file.** Its path and name do not change, so
   shortcuts and desktop entries keep working; the name then shows the version
   first downloaded.
5. **Releases are signed on this PC** after GitHub builds them, with a key kept
   only here (ADR-0008).
6. **Nothing downloads without a click** (ADR-0008).
7. **A checkout is never offered an update** (ADR-0008) — git and uv own it.
   Decided here: it makes no request at all, and its Settings dialog shows no
   update switch.
8. **A manual "Check for updates" entry** in the Settings menu — decided here,
   so a user who turned the start-up check off can still ask. AppImage only.

## 4. Design

### 4.1 Modules

| File | Holds | Layer (`coding-overrides.md` § O1) |
| --- | --- | --- |
| `src/lwsm/update.py` (new) | install kind, version grammar, release parsing, the offer, signature verification, the swap, the relaunch | core, no Qt |
| `src/lwsm/update_key.py` (new) | `RELEASE_PUBLIC_KEY_B64`, `public_key()` | core, no Qt |
| `src/lwsm/update_fetch.py` (new) | the release-list check and the asset download, on `QNetworkAccessManager` | core: `QtCore` and `QtNetwork` |
| `src/lwsm/updatedialog.py` (new) | the non-modal update window | UI |
| `src/lwsm/mainwindow.py` | the update banner, the menu entry, starting the check | UI |
| `src/lwsm/settings.py`, `settingsdialog.py` | two new settings, one checkbox | as now |
| `src/lwsm/__main__.py` | reads `APPIMAGE` before the scrub | entry |
| `scripts/sign-release.py` (new) | make the key pair, check the key, sign and publish a release's signature | tooling |

`update_fetch.py` is the only module that makes a request to the internet
(INV-12). O1's rule row changes from "`QtCore` only" to "`QtCore`, and
`QtNetwork` in `update_fetch.py`": `QtNetwork` needs no display, which is what
O1 protects.

### 4.2 Install kind

```python
# update.py
def install_kind(frozen: bool, appimage: str | None) -> str:
    """'appimage' when frozen and appimage names an existing regular file;
    'checkout' otherwise."""
```

`main` reads `os.environ.get("APPIMAGE")` **before** `_forget_bundle_environment`
and passes `install_kind(getattr(sys, "frozen", False), value)` and the path to
the window builder. Nothing reads `APPIMAGE` from the environment after that.

### 4.3 The release list and the version grammar

One request per check:

```
GET https://api.github.com/repos/milnet01/LocalWebServerManager/releases?per_page=30
Accept: application/vnd.github+json
User-Agent: LocalWebServerManager/<__version__>
```

GitHub refuses an API request with no `User-Agent`, and Qt sends none by
default (`QNetworkRequest().header(UserAgentHeader)` → `None`, PySide6 6.12.0,
2026-11-11). The header names the app and its version, nothing about the user.

```python
# update.py
APPIMAGE_ASSET = "LocalWebServerManager-{version}-x86_64.AppImage"
SIGNATURE_ASSET = APPIMAGE_ASSET + ".sig"

def parse_version(tag: str) -> tuple[int, int, int] | None:
    """'v0.6.0' / '0.6.0' -> (0, 6, 0). Exactly three dot-separated parts, each
    str.isascii() and str.isdigit(), one leading v or V allowed. Else None."""

@dataclass(frozen=True)
class Release:
    version: tuple[int, int, int]
    body: str                  # the release notes, Markdown; may be ""
    appimage_url: str | None   # browser_download_url of APPIMAGE_ASSET
    signature_url: str | None  # browser_download_url of SIGNATURE_ASSET
    appimage_size: int         # the asset's "size"; 0 when absent

def releases_from_json(data: object) -> list[Release] | None:
    """None when data is not a list. Otherwise every dict entry that is not a
    draft or prerelease and whose tag_name parses, highest version first. A
    malformed entry is dropped, never raised. An asset counts only when its
    name is the pattern filled with THIS release's version, and its URL starts
    with https://."""

Version = tuple[int, int, int]   # parse_version's result; callers parse

def changelog(releases, installed: Version, offered: Version) -> list[Release]:
    """installed < r.version <= offered, highest first."""

def offer(releases, installed: Version, skipped: Version | None) -> Release | None:
    """The highest release above installed carrying both asset URLs, unless
    its version equals skipped. None when update_key.public_key() is None."""
```

Each release body is that version's CHANGELOG section: 0.5.1's begins
"**Theme:** A download that needs nothing installed first"
(`gh release view v0.5.1 --json body`, 2026-11-11). A tag such as `v1.0.0-rc.1`
fails `parse_version` and is never offered.

### 4.4 When the check runs

- **At start-up**, once the window is shown, when the install kind is
  `appimage` and `Settings.update_check` is true.
- **From Settings → Check for updates**, shown only for `appimage`.

A failed check at start-up writes one `app.log` line and shows nothing. A
manual check reports through `MainWindow.set_status_message`: "No update is
ready to install.", "Couldn't reach GitHub to check for updates.", or "Couldn't
read GitHub's reply." An offer found by either opens the banner (§4.5); a
manual check also opens the window. A manual check calls `offer` with
`skipped=None`, so it offers a skipped version too.

### 4.5 The banner and the window

**The banner** is a second frame beside `MainWindow._banner`, so a status
message never replaces the offer: "Version {offered} is available." and a
**What's new** button. It hides when the offer is skipped or installed.

**The window**, `updatedialog.UpdateDialog(QDialog)`, parented to the main
window and opened with `show()`, never `exec()`. A visible parentless dialog
keeps `app.exec()` running after the main window closes (PySide6 6.12.0,
2026-11-11), and §4.7's waiter would then wait out its limit.

- Heading: "Version {offered} is available. You have {installed}."
- A read-only `QTextBrowser` subclass holding each version from
  `changelog()` under a "Version X.Y.Z" heading, newest first, set with
  `document().setMarkdown(text, MarkdownDialectGitHub | MarkdownNoHTML)`;
  `QTextBrowser.setMarkdown` takes no feature flags. Its
  `loadResource` returns nothing for every URL, and `openLinks` and
  `openExternalLinks` are both false, so the notes load no file, fetch nothing
  and open nothing.
- Buttons: **Update now**, **Skip this version**, **Later**, each with
  `setAutoDefault(False)`, so none is the default and Enter installs nothing.
  A `QPushButton` in a `QDialog` is auto-default, and the first becomes the
  default when shown (PySide6 6.12.0, 2026-11-11).
- During a download: a progress bar, determinate from `appimage_size`, and
  **Cancel** in place of the buttons.
- Every control has an accessible name; every string goes through `self.tr`;
  no fixed geometry, so the text-size setting reflows it.

**Skip this version** stores the offered version in `Settings.update_skip` and
hides the banner. **Later** closes the window and stores nothing.

### 4.6 Download, verify, install

1. `update_fetch` downloads the `.sig`, then the AppImage, each into memory
   on its own `QNetworkAccessManager`, so no reply reaches another request's
   handler. Every request is `https://`; Qt's default
   `NoLessSafeRedirectPolicy` follows GitHub's redirect to its download host
   and refuses a downgrade, and the reply's final URL is checked to be
   `https://` as well.
2. Caps, counted on the bytes received rather than on `Content-Length`: the
   list 1 MiB, the `.sig` 1 KiB and then exactly 64 bytes, the AppImage
   256 MiB. 0.5.1's AppImage is 48,560,632 bytes (`gh release view v0.5.1
   --json assets`, 2026-11-11). Each request sets a 30-second transfer
   timeout, which Qt counts from the last byte received.
3. `update.verify(data, signature, version)` raises `UpdateVerificationError`
   unless `public_key().verify(signature, message)` passes, where
   `message = b"LocalWebServerManager " + version.encode() + b"\n" + data` and
   `version` is the offered `X.Y.Z`. Binding the version means a genuine older
   AppImage and its `.sig`, attached to a newer tag, fails.
4. Only then `update.install(data, appimage)`.

**Nothing downloaded touches the disk before it verifies**, and the bytes
verified are the bytes written.

```python
def install(data: bytes, appimage: str) -> Path:   # update.py
    """target = Path(os.path.realpath(appimage)). Raise UpdateInstallError,
    writing nothing, when os.access(target.parent, os.W_OK) is false. Write
    data to tempfile.mkstemp(prefix=".lwsm-update-", dir=target.parent),
    fchmod it to target's mode, fsync, os.replace(temp, target), fsync the
    folder. Any exception before os.replace unlinks the temp and leaves target
    untouched. Returns target."""
```

`realpath` because `APPIMAGE` may be a symlink. **No root, ever**: a file in a
folder the user cannot write is reported — "The app can't replace itself in
{folder}." — and left alone. Replacing the file while it runs is safe:
`os.replace` gives the path a new file, and the running copy keeps the old one
open through its mount.

### 4.7 The relaunch

```python
def relaunch(target: Path) -> None:   # update.py
    """subprocess.Popen([*supervisor.scope_prefix(os.environ), '/bin/sh',
    '-c', WAITER, 'sh', str(os.getpid()), str(target)],
    start_new_session=True, env=dict(os.environ),
    stdin/stdout/stderr=DEVNULL). The caller then closes the main window
    through its normal close path."""
```

- **`WAITER` polls every 0.1 s, for at most 60 s, until the pid has gone**,
  a zombie counting as gone, then `exec`s the target. Waiting is what lets the
  new copy own the single-instance socket (§2 item 3).
- **In a systemd scope of its own**, as each server is (ADR-0003, LWSM-1420).
  A desktop launch runs the app in a transient service with
  `KillMode=control-group`, and a new session stays in that cgroup. Measured
  2026-11-11 with `systemd-run --user`: a `start_new_session` child died when
  the service's main process exited. Where `scope_prefix` returns `()`, the
  waiter starts plainly.
- **One pid**, because `AppRun` `exec`s the frozen app and `--onedir` has no
  bootloader parent (§2).
- **The environment is `os.environ` as the app holds it**: `run` and `main`
  have already restored the launch library path and removed the AppImage and
  `_PYI_*` variables.
- **Never `os.exec*`**: it cannot replace the busy mount (finbreak 0.1.2).
- **Servers keep running.** They outlive the window (ADR-0003), and the new
  copy finds them by probing (ADR-0004).

### 4.8 Settings

`Settings` gains two fields, inside schema v1:

```python
update_check: bool = True          # §3 item 2
update_skip: str | None = None     # "X.Y.Z"; parse_version must accept it
```

`load` reads `update_check` with `_bool_or_reason`, reads a `null`
`update_skip` as `None` with no reason, and refuses any other value that
`parse_version` rejects, with a reason, keeping `None`.
`_payload` writes both, `update_skip` as `null` while unset: `load` takes
its known keys from `_payload(Settings())`. An older build carries
both through `Settings.unknown` (LWSM-1289). `SettingsDialog` gains "Check for
updates when the app starts", shown only for `appimage`.

### 4.9 Signing a release

`scripts/sign-release.py`, run on this PC with `uv run`:

- **`generate`, once, by the user.** Writes the private key to
  `~/.config/lwsm-release/signing.key` (mode 600, refusing to overwrite) and
  prints the public key's base64, which goes into
  `update_key.RELEASE_PUBLIC_KEY_B64`. The private key never enters the
  repository or a Claude session. **Back it up**: with it lost, every
  installed AppImage refuses all later updates until its user downloads one
  by hand.
- **`check-key`** exits 0 when the key file is the private half of the
  committed public key, 1 otherwise, and prints only that answer.
  `scripts/local-release.sh` runs it as a release STOP when given a target
  version.
- **`publish X.Y.Z`**, after the release is published: waits for that tag's
  Release workflow (`gh run watch`), downloads the AppImage into a temporary
  folder, signs it for `X.Y.Z`, verifies the signature through
  `update.verify` against the **committed** key, and uploads the `.sig` with
  `gh release upload --clobber`. Any failure exits non-zero and uploads
  nothing; the release then carries no `.sig` and is offered to no one.
- A tag moved after publishing rebuilds the AppImage; `publish` is run again
  and replaces the `.sig`.

`docs/claude/release.md` gains the `publish` step. `.gitignore` gains `*.key`.
Until the user runs `generate`, `RELEASE_PUBLIC_KEY_B64` is empty,
`public_key()` returns `None`, and nothing is ever offered (§4.3's `offer`).

### 4.10 Dependency and bundle

`cryptography`, pinned exactly at its release on the day of implementation,
joins `[project] dependencies`; `uv.lock` resolves `cffi` and `pycparser`
beneath it. `scripts/_appimage-build.sh` fails the build when the frozen
folder lacks `cryptography/hazmat/bindings/_rust.abi3.so`, so a bundle that
cannot verify is never released.

## 5. Invariants

- **INV-1** — `install_kind` is `appimage` only when frozen and `appimage`
  names an existing regular file; `main` reads `APPIMAGE` before
  `_forget_bundle_environment` removes it.
  *Test:* `tests/test_update.py` — frozen with a real file → `appimage`; not
  frozen with a real file, frozen with `None`, frozen with a missing path,
  frozen with a folder → `checkout`. `tests/test_main.py` — `sys.frozen`
  patched, `APPIMAGE` set: the window builder receives the path.
  *Breaks when:* `APPIMAGE` is read after the scrub, or alone without
  `sys.frozen`.

- **INV-2** — `parse_version` accepts exactly `[vV]?D.D.D` with ASCII digits.
  *Test:* `tests/test_update.py` — `0.6.0`, `v0.6.0` accepted; `0.6.0-rc.1`,
  `0.6`, `0.6.0.1`, `latest`, `0.¹.0` and the empty string rejected.
  *Breaks when:* the digit test omits `isascii()` (`'¹'.isdigit()` is true),
  or a fourth part is allowed.

- **INV-3** — `releases_from_json` returns `None` for a non-list, never
  raises, and drops drafts, prereleases, non-dicts, unparseable tags,
  non-HTTPS asset URLs and assets named for another version; `changelog`
  returns exactly `installed < v <= offered`, highest first.
  *Test:* `tests/test_update.py` — a fixture with one entry of each bad kind;
  a JSON object → `None`; installed `0.5.1`, offered `0.7.0` over `0.5.1,
  0.8.0, 0.4.0, 0.6.0, 0.7.0` → `[0.7.0, 0.6.0]`.
  *Breaks when:* a dict reply is read as an empty list, or an asset is matched
  by suffix alone, so an older version's file attached to a newer tag counts.

- **INV-4** — `offer` returns the highest release above `installed` that
  carries both assets, `None` when that release's version is `skipped`, and
  `None` while `public_key()` is `None`.
  *Test:* `tests/test_update.py` — releases `0.7.0` (unsigned) and `0.6.0`
  (signed) over installed `0.5.1` → `0.6.0`; skipped `0.6.0` → `None`;
  `0.8.0` signed beside a skipped `0.6.0` → `0.8.0`; signed `0.7.0` skipped
  over signed `0.6.0` → `None`; empty public key → `None`.
  *Breaks when:* the skip is compared with `<=`, silencing every later
  version, or an unsigned release is offered.

- **INV-5** — `verify` passes only for a 64-byte Ed25519 signature, by the
  key in `update_key`, over the prefix, the offered version and the exact
  bytes. This is the trust boundary.
  *Test:* `tests/test_update.py` — a throwaway key patched into `update_key`;
  good bytes → returns; one flipped data byte, one flipped signature byte, a
  63-byte signature, a signature made for another version, and one from a
  second key → each raises `UpdateVerificationError`.
  *Breaks when:* the version is left out of the signed message, or a
  verification error is caught and ignored.

- **INV-6** — The downloaded bytes reach the disk only through `install`,
  after `verify` returns.
  *Test:* `tests/test_update_fetch.py` — the download handler driven with
  injected replies; the target folder and `tempfile.gettempdir()` listed
  before `verify` returns → nothing new; a `.sig` that fails `verify` →
  `install` never called, the target byte-identical.
  *Breaks when:* the download streams to a temporary file that is verified
  and then re-read.

- **INV-7** — `install` writes beside the real file, keeps its mode and
  replaces it atomically; a failure before the replace leaves the original
  byte-identical and no temporary file behind.
  *Test:* `tests/test_update.py` — a 0755 target reached through a symlink →
  the link still a link, the real file holding the new bytes at 0755;
  `os.replace` patched to raise → original unchanged, folder listing
  unchanged.
  *Breaks when:* the temporary file is made in `/tmp` (a cross-filesystem
  `os.replace` raises `EXDEV`), or the symlink is replaced instead of its
  target.

- **INV-8** — The update never asks for root: an unwritable folder is refused
  before anything is written.
  *Test:* `tests/test_update.py` — a target in a 0555 folder →
  `UpdateInstallError`, nothing written; an AST walk of `update.py` finds no
  string naming `sudo` or `pkexec`.
  *Breaks when:* an unwritable folder falls back to a privileged copy.

- **INV-9** — `relaunch` starts `/bin/sh` behind `scope_prefix`'s argv, in a
  new session, with the waiter, this pid and the target, in the app's current
  environment, and never calls `os.exec*`; the waiter execs once the pid has
  gone, or at its 60 s limit.
  *Test:* `tests/test_update.py` — `subprocess.Popen` patched to record: argv
  and `start_new_session=True` as specified, `env` equal to `os.environ`; the
  waiter run for real against a child `sleep 0.5` → it exits after the child,
  not before. The relaunch inside a real AppImage is §7's manual recipe.
  *Breaks when:* the relaunch is an `execv`, the waiter stays in the app's
  cgroup and dies with it, or the new copy starts while the old one still
  holds the single-instance socket.

- **INV-10** — Every read is capped on bytes received: the list at 1 MiB, the
  `.sig` at 1 KiB and exactly 64 bytes, the AppImage at 256 MiB; an over-cap
  read aborts and keeps nothing.
  *Test:* `tests/test_update_fetch.py` — each handler fed one byte over its
  cap with no `Content-Length` → aborted, nothing kept.
  *Breaks when:* a cap is checked on `Content-Length` only, which a server may
  omit.

- **INV-11** — Every request is `https://`, and a reply whose final URL is not
  `https://` is refused.
  *Test:* `tests/test_update_fetch.py` — a release whose asset URL is
  `http://` never reaches a request (INV-3 drops it); an injected reply with a
  final URL of `http://` → refused, nothing kept.
  *Breaks when:* the final URL goes unchecked and a later change to the
  redirect policy lets a redirect drop to `http://`.

- **INV-12** — `update_fetch.py` is the only module under `src/lwsm/` that
  imports `QNetworkAccessManager`, `urllib`, `http.client` or `socket`, except
  `health.py`, whose `http.client` and `socket` reach `localhost` only.
  *Test:* `tests/test_layering.py`, an AST walk like its others — a planted
  `import urllib.request` in a scratch copy of another module → flagged.
  *Breaks when:* the download moves into `update.py` or a UI module.

- **INV-13** — The notes window loads no resource, opens no link and renders no
  HTML.
  *Test:* `tests/test_updatedialog.py` — `QDesktopServices.openUrl` patched to
  record; notes holding a link, an `![x](file:///etc/hostname)` image and a
  `<b>raw</b>` span; the link activated → nothing recorded; `loadResource`
  never returns data; the document's plain text contains `<b>raw</b>`
  literally.
  *Breaks when:* the notes go through a `QLabel` with rich text, or the
  `MarkdownNoHTML` flag is dropped.

- **INV-14** — The window is non-modal and every control in it has an
  accessible name; no button is the default.
  *Test:* `tests/test_updatedialog.py` — after `show()`, `isModal()` is false,
  every `QAbstractButton` and the notes browser has a non-empty
  `accessibleName()`, and no `QPushButton.isDefault()`; an AST walk finds no
  `.exec(` in `updatedialog.py`.
  *Breaks when:* the window is opened with `exec()`, blocking the project
  list, or Enter installs.

- **INV-15** — The start-up check runs only for `appimage` with
  `update_check` on; a failed start-up check shows nothing, a failed manual
  check reports, and neither raises out of a slot.
  *Test:* `tests/test_mainwindow.py` — the check entry point replaced by a
  recorder: `checkout` → not called; `appimage` with the setting off → not
  called; on → called once. Injected HTTP 403, non-JSON and JSON-object
  replies → no banner and no status message at start-up; the §4.4 wording on
  a manual check.
  *Breaks when:* a checkout makes a request, or a non-list body is read as
  "up to date".

- **INV-16** — Skip this version persists the version and hides that
  version's banner across launches; a newer version is offered again; Later
  stores nothing.
  *Test:* `tests/test_mainwindow.py` — Skip on `0.6.0`, a new window, an offer
  of `0.6.0` → no banner; a manual check finding `0.6.0` → banner; `0.7.0`
  → banner; Later → `update_skip` unchanged.
  *Breaks when:* the skip is stored only in memory, or compared with `<=`.

- **INV-17** — `update_check` and `update_skip` round-trip through `save` and
  `load`; a malformed `update_skip` is refused with a reason and read as
  `None`; a file without them gets the defaults.
  *Test:* `tests/test_settings.py` — round-trip of `False`/`"0.6.0"`, and of
  `Settings()` with no reason;
  `"0.6"` and `7` → `None` with one reason each; an older file → `True`/`None`.
  *Breaks when:* a malformed skip reaches `offer`, or a missing key reads as
  off.

- **INV-18** — No private key is tracked, and `sign-release.py` round-trips:
  a signature it makes verifies through `update.verify` with the matching
  public key; `check-key` answers without printing key material.
  *Test:* `tests/test_sign_release.py` — `git ls-files` holds no `*.key` and
  no file matching `-----BEGIN [A-Z ]*PRIVATE KEY-----`; a throwaway pair
  generated in a temporary home, a file signed and verified → passes;
  verified against a second key → `UpdateVerificationError`; `check-key`
  exits 0 on the matching key, 1 on a second key, 1 on a missing file, and
  its output never contains the key's base64.
  *Breaks when:* the signer signs a hash while the verifier checks the bytes,
  or `generate` overwrites an existing key.

- **INV-19** — A released bundle can verify: the AppImage build fails when the
  frozen folder lacks `cryptography`'s compiled binding.
  *Test:* `scripts/_appimage-build.sh`'s check, seen failing once with the
  file removed from a scratch copy of the frozen folder.
  *Breaks when:* PyInstaller stops collecting `cryptography`, and an AppImage
  that refuses every update ships.

## 6. Failure modes

| What goes wrong | What the user sees | Why it is safe |
| --- | --- | --- |
| GitHub unreachable or rate-limited | nothing at start-up; a message on a manual check | no offer is made (INV-15) |
| The newest release has no `.sig` | no offer for it; its notes appear under a later signed version | INV-4 |
| No public key committed yet | no offer, ever | INV-4 |
| Download interrupted, timed out or cancelled | "The download didn't finish." and the buttons return | nothing was written (INV-6) |
| Signature fails | "This download couldn't be proved to come from the app's author, so it was not installed." | INV-5 |
| Folder not writable | "The app can't replace itself in {folder}." | no root (INV-8) |
| Disk full during the write | the `OSError` reported; the old AppImage runs on | INV-7 |
| The old copy does not exit within 60 s | the new copy starts, finds the old one and hands over to it | the file is already new; the next start runs it |
| `/bin/sh` cannot start | the app closes and does not reopen | the next launch runs the new file |
| The signing key is lost | releases ship unsigned; no AppImage is offered them | users download one by hand once (§4.9) |
| A GitHub account compromise swaps the AppImage, or re-attaches an older signed one to a newer tag | the asset fails verification | the key is not on GitHub (§3 item 5); the signature covers the version (§4.6) |
| The CI build itself is compromised before signing | **not defended**: this PC signs what CI built | residual risk of §3 item 5; the build's inputs are pinned (`uv.lock`, SHA-pinned actions) |

## 7. Tests

| Invariant | Where |
| --- | --- |
| INV-1, INV-2, INV-3, INV-4, INV-5, INV-7, INV-8, INV-9 | `tests/test_update.py` (new), no Qt, no network, a throwaway key |
| INV-1's `main` half | `tests/test_main.py` |
| INV-6, INV-10, INV-11 | `tests/test_update_fetch.py` (new): the reply handlers driven with injected status, final URL and byte chunks; no request leaves the machine |
| INV-12 | `tests/test_layering.py` |
| INV-13, INV-14 | `tests/test_updatedialog.py` (new), `qtbot` |
| INV-15, INV-16 | `tests/test_mainwindow.py`, the check entry point replaced |
| INV-17 | `tests/test_settings.py` |
| INV-18 | `tests/test_sign_release.py` (new) |
| INV-19 | `scripts/_appimage-build.sh` |

Each test is seen failing against a tree without its rule before it is called
green. The new modules join `CORE_MODULES` or `NON_CORE_MODULES` in
`tests/test_layering.py`.

**What no suite covers**: the relaunch inside a real AppImage on a real
desktop — the FUSE mount, `AppRun`'s `exec` and the single-instance handover.
**Manual recipe**, run on the first two signed releases: run AppImage N from
the desktop menu, publish N+1 signed, press What's new → Update now. The app closes and reopens
on N+1 within a few seconds, with one window, and a server it had started
still reads `running`. Then once with the AppImage reached through a symlink.

## 8. Alternatives considered (and rejected)

- **Register with OneUp** — not possible without changing OneUp (ADR-0008).
- **A notice linking to the release page; no check at all** — rejected by the
  user (ADR-0008).
- **Sign in CI with a GitHub secret** — rejected by the user: whoever got into
  the account could sign a fake update.
- **A hand-written Ed25519 verifier** — rejected by the user: it saves one
  dependency at the cost of security code written here, where a subtle mistake
  accepts a fake update.
- **Python's `urllib` for the download** — rejected: the bundle's OpenSSL
  looks for CA certificates where the build container keeps them, which is not
  where every distribution does; it would need `certifi` as a fourth
  dependency. Qt's backend reads the host's store and is already bundled.
- **Rename the file to the new version** — rejected by the user: every
  shortcut to the old name breaks.
- **Download to a temporary file, then verify** — rejected: the gap between
  check and use that finbreak's FIBR-0170 closed. 256 MiB in memory is
  affordable for a one-off.
- **`os.execv` for the relaunch** — rejected: finbreak 0.1.2's bug (§4.7).
- **`PYINSTALLER_RESET_ENVIRONMENT=1` and restoring `<VAR>_ORIG` in the
  relaunch, as OneUp does** — not needed: `run` and `main` already clean the
  environment for every child (§2), and a second copy of that cleaning would
  be a second rule to keep in step.
- **Sign a `SHA256SUMS` file** — rejected: there is one asset, and signing the
  version with the bytes gives the same binding without a second file.

## 9. Out of scope

- Rotating the signing key — deferred; not yet queued.
- Background or automatic downloads (§3 item 6) — deferred; not yet queued.
- A test that verifies a real signed release against the committed key — it
  needs a signed release first; deferred; not yet queued.
- Updating a checkout — git's and uv's job (§3 item 7).

## 10. What checks this

| Rule | What catches a breach |
|------|----------------------|
| INV-1 | `tests/test_update.py`, `tests/test_main.py` |
| INV-2, INV-3, INV-4, INV-5, INV-7, INV-8, INV-9 | `tests/test_update.py` |
| INV-6, INV-10, INV-11 | `tests/test_update_fetch.py` |
| INV-12 | `tests/test_layering.py` |
| INV-13, INV-14 | `tests/test_updatedialog.py` |
| INV-15, INV-16 | `tests/test_mainwindow.py` |
| INV-17 | `tests/test_settings.py` |
| INV-18 | `tests/test_sign_release.py` |
| INV-19 | `scripts/_appimage-build.sh` |
| The relaunch in a real AppImage | **nothing** automatic — §7's manual recipe |
| The release is signed after publishing | Partial: `local-release.sh` stops on a missing or wrong key; nothing checks that `publish` was run — a release without a `.sig` is offered to no one, which is safe and silent |
| The CI build is what was reviewed | **nothing** — §6's residual risk |

## 11. Cross-doc impact

- `docs/decisions/0008-updates-reach-users.md` § Consequences: the signing
  step is `scripts/sign-release.py publish`, run after publishing, not
  `scripts/local-release.sh`, which is a preflight.
- `docs/standards/coding-overrides.md` § O1: the core may import `QtNetwork`
  in `update_fetch.py`.
- `docs/claude/release.md`: the `publish` step and the one-time key setup.
- `docs/claude/module-map.md`: the four new modules.
- `pyproject.toml`: the dependency comment (§3 item 3).
- `CHANGELOG.md` `[Unreleased]`: Added — the AppImage updates itself.
- `README.md`: the AppImage updates itself from this version on; earlier
  versions download once by hand.

## 12. Cold-eyes loop log

Rows live in `../reviews/LWSM-1548-appimage-self-update-loop-log.md`.

## 13. Resource cost

- **Memory**: the AppImage is held in memory during a download, capped at
  256 MiB, and released when the install or the failure ends.
- **Network**: one request to GitHub per start, and none with the setting
  off; GitHub's unauthenticated budget is 60 an hour per address.
- **Bundle**: `cryptography`'s x86-64 wheel for 50.0.2 is 4,749,145 bytes
  (PyPI, 2026-11-11); the AppImage grows by about that.

## 14. Migration / compatibility

- **0.5.1 and earlier have no updater.** Their users download the first
  self-updating release by hand, once.
- **`settings.json`** gains two keys inside schema v1. An older build keeps
  them through `Settings.unknown`.
- **A relaunch fix reaches users one release late**: the version doing the
  relaunch is the old one (ADR-0008).

## 15. Open questions

- Whether `WAITER`'s one pid is enough on every AppImage runtime: the type-2
  runtime keeps a FUSE helper process alive while the app runs. The new file
  is a new inode, so the helper should not matter; §7's recipe is the check.
