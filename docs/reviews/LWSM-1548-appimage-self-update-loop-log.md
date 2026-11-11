# LWSM-1548 AppImage self-update loop log

## Cold-eyes loop log

Review rows for `docs/specs/LWSM-1548-appimage-self-update.md`.

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| 1 | 2026-11-11 | 2 (`review-lane` via `neutral-lane`; every lane held every question, whole document) | 3 | 2 | 2 | 0 | 7 verified, 7 fixed, 4 dismissed or resolved. Packet build found 2 Q1: `QTextBrowser.setMarkdown` takes no feature flags (now `document().setMarkdown`), and writing `update_skip` only when set would break `load`'s known keys (now written as `null`). Lanes: the waiter stayed in a desktop launch's cgroup and died with the app (now behind `supervisor.scope_prefix`; measured with `systemd-run --user`); INV-9's "execs only after the pid has gone" against §6's 60 s row; `offer`'s docstring against INV-4 on a skipped top release (INV-4 now follows the docstring); the dialog's parent was unpinned, and a parentless one keeps `app.exec()` running (measured); a manual check reported a skipped release as "the newest version" (now `skipped=None`). One false clause deleted outside the tally (§4.7, "the same environment every server's launcher gets"). Resolved by measurement: Qt's transfer timeout restarts on each byte. Unrunnable region: the relaunch in a real AppImage (§7's recipe). |
