"""The Preferences dialog (LWSM-1018).

UI layer — imports QtWidgets, so no core module may import it back
(`docs/standards/coding.md § O1`, enforced by `tests/test_layering.py`).

**It edits three fields, not the four the roadmap bullet filed**, and both
absences were settled with the user on 2026-08-21 rather than dropped quietly:

- *Scan roots* are not moved into `settings.json`. They live in the `scan-roots`
  file (LWSM-1144), whose own docstring says this dialog owns the UI while that
  file is the setting. Editing it in place means one owner and no migration;
  copying it into `settings.json` would mean both, for no user-visible gain.
- There is no *slow-start threshold*. ADR-0004 § Slowness is not failure
  deleted the 15-second `starting` deadline on 2026-08-03, on the measured
  evidence of a healthy project that takes about 40 seconds to bind. A setting
  for it would re-introduce exactly the defect that ADR reversed.

**The dialog owns no I/O.** It is handed values and returns values; reading and
writing the two files is `__main__`'s, which is the only place a settings file
and a scan-roots file are both in scope. That is the same split
`MainWindow._save_theme` takes, and for the same reason: a widget that writes
to the developer's own config the moment a test constructs it is a widget no
test can exercise.

**`choose_directory` is injected** for the reason `MainWindow._confirm` is: a
real `QFileDialog.getExistingDirectory()` in a test blocks the event loop with
nothing to click, which is a hang rather than a failure.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from lwsm.mainwindow import MIN_TARGET_PX
from lwsm.settings import (
    MAX_LOG_MAX_MIB,
    MAX_POLL_INTERVAL_MS,
    MIN_LOG_MAX_MIB,
    MIN_POLL_INTERVAL_MS,
)

_TR_CONTEXT = "SettingsDialog"

# The spinbox step for the poll interval. A quarter of a second, so the arrows
# walk the range in a sane number of presses rather than one millisecond at a
# time — the keyboard is a first-class way to drive this (`§ O8`).
POLL_STEP_MS = 250


class SettingsDialog(QDialog):
    """Scan roots, poll interval and log cap, as one modal form."""

    def __init__(
        self,
        *,
        roots: Sequence[Path],
        poll_interval_ms: int,
        log_max_mib: int,
        choose_directory: Callable[[], str | None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._choose_directory = (
            choose_directory if choose_directory is not None else self._pick_directory
        )
        self.setModal(True)

        self._roots = QListWidget()
        # The list is the one control here that can be empty and still be
        # correct: no roots means "scan the default", which is what
        # `default_scan_roots` falls back to. So there is no validation on it.
        for root in roots:
            self._roots.addItem(str(root))
        self._roots.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

        self._add = QPushButton()
        self._add.clicked.connect(self._add_root)
        self._remove = QPushButton()
        self._remove.clicked.connect(self._remove_roots)
        for button in (self._add, self._remove):
            # The same floor `ProjectRow` puts under its buttons, and in the
            # source rather than only in a test: LWSM-1032 measured 25 px on
            # this machine and 22 px on the CI runner, so the ambient font
            # decides whether the floor is cleared and the suite cannot see it.
            button.setMinimumHeight(MIN_TARGET_PX)
            button.setMinimumWidth(MIN_TARGET_PX)

        self._poll = QSpinBox()
        self._poll.setRange(MIN_POLL_INTERVAL_MS, MAX_POLL_INTERVAL_MS)
        self._poll.setSingleStep(POLL_STEP_MS)
        self._poll.setValue(poll_interval_ms)

        self._log = QSpinBox()
        self._log.setRange(MIN_LOG_MAX_MIB, MAX_LOG_MAX_MIB)
        self._log.setValue(log_max_mib)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        # The same floor, over every remaining control rather than the two
        # buttons above (LWSM-1206). A spinbox is dragged and clicked on its
        # arrows, and Ok and Cancel are the two most important targets in the
        # dialog; all four were under 24 px at a small system font.
        #
        # Asked of each BUTTON, never of `self._buttons`. The box is a
        # container, and `keyboard_focus_order` already records the same trap
        # for focus: its own policy is NoFocus while the buttons inside it are
        # focusable, so a property set or read on the box says nothing about
        # what the user actually clicks.
        for target in (
            self._poll,
            self._log,
            self._buttons.button(QDialogButtonBox.StandardButton.Ok),
            self._buttons.button(QDialogButtonBox.StandardButton.Cancel),
        ):
            target.setMinimumHeight(MIN_TARGET_PX)
            target.setMinimumWidth(MIN_TARGET_PX)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        self._roots_label = QLabel()
        self._roots_label.setBuddy(self._roots)
        self._poll_label = QLabel()
        self._poll_label.setBuddy(self._poll)
        self._log_label = QLabel()
        self._log_label.setBuddy(self._log)

        buttons = QHBoxLayout()
        buttons.addWidget(self._add)
        buttons.addWidget(self._remove)
        buttons.addStretch(1)

        roots_column = QVBoxLayout()
        roots_column.addWidget(self._roots)
        roots_column.addLayout(buttons)

        form = QFormLayout()
        form.addRow(self._roots_label, roots_column)
        form.addRow(self._poll_label, self._poll)
        form.addRow(self._log_label, self._log)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)

        # Set here rather than at construction, so `changeEvent` has one place
        # to go on a language change — the rule `_retranslate_menus` follows.
        self._retranslate()

    def _retranslate(self) -> None:
        """Every user-visible string, in one method (`§ O8` clause 1).

        Each label carries an `&` mnemonic and a buddy, so the form is
        keyboard-reachable without a mouse: Alt+S lands in the list, Alt+P and
        Alt+L in the two spinboxes.
        """
        self.setWindowTitle(QCoreApplication.translate(_TR_CONTEXT, "Preferences"))
        self._roots_label.setText(
            QCoreApplication.translate(_TR_CONTEXT, "&Scan these folders:")
        )
        self._poll_label.setText(
            QCoreApplication.translate(_TR_CONTEXT, "Check &how often:")
        )
        self._log_label.setText(
            QCoreApplication.translate(_TR_CONTEXT, "Keep at most this much &log:")
        )
        self._add.setText(QCoreApplication.translate(_TR_CONTEXT, "&Add..."))
        self._remove.setText(QCoreApplication.translate(_TR_CONTEXT, "&Remove"))
        # A suffix rather than a unit baked into the label, so the value and
        # its unit are announced together by a screen reader.
        self._poll.setSuffix(QCoreApplication.translate(_TR_CONTEXT, " ms"))
        self._log.setSuffix(QCoreApplication.translate(_TR_CONTEXT, " MiB"))
        self._roots.setAccessibleName(
            QCoreApplication.translate(_TR_CONTEXT, "Folders to scan for projects")
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
        super().changeEvent(event)

    def _pick_directory(self) -> str | None:
        """The real folder chooser, used whenever nothing was injected."""
        chosen = QFileDialog.getExistingDirectory(
            self, QCoreApplication.translate(_TR_CONTEXT, "Choose a folder to scan")
        )
        return chosen or None

    def _add_root(self) -> None:
        chosen = self._choose_directory()
        if not chosen:
            # Cancelled. Not an error, and nothing to report.
            return
        # Compared as text, which is what the list holds and what the file
        # stores. Resolving here would rewrite a path the user typed by hand
        # into one they may not recognise, and `scanner.scan` already resolves
        # for its own containment test.
        existing = {self._roots.item(row).text() for row in range(self._roots.count())}
        if chosen not in existing:
            self._roots.addItem(chosen)

    def _remove_roots(self) -> None:
        # The row is looked up FRESH on each pass, which is the whole trick:
        # removing a row renumbers every row below it, and asking the item
        # where it is now gets the answer after that renumbering. Collecting
        # the indices up front and then deleting them is the version that
        # removes the wrong entries as soon as two are selected.
        #
        # An earlier draft also sorted bottom-up. A mutation flipping that sort
        # survived the suite, which is what showed the sort was doing nothing:
        # the fresh lookup already closes the hazard it was guarding.
        for item in self._roots.selectedItems():
            self._roots.takeItem(self._roots.row(item))

    def values(self) -> tuple[tuple[Path, ...], int, int]:
        """What the user chose: roots, poll interval in ms, log cap in MiB.

        Read after `exec()` returns `Accepted`. The spinboxes cannot report a
        value outside their range, so there is nothing to validate here — and
        `settings.load` re-checks the range anyway, because the file is
        hand-editable and this dialog is not the only way in.
        """
        roots = tuple(
            Path(self._roots.item(row).text()) for row in range(self._roots.count())
        )
        return roots, self._poll.value(), self._log.value()


def keyboard_focus_order(dialog: SettingsDialog) -> tuple[Qt.FocusPolicy, ...]:
    """The focus policy of each control, in tab order. Used by the tests.

    An accessor that names the contract rather than one that exposes the
    widgets: what `§ O8` requires is that every control can be reached from the
    keyboard, and that is a statement about focus policies, not about the
    widget tree.

    Ok and Cancel are listed individually rather than as the `QDialogButtonBox`
    holding them. The box is a container and its own focus policy is `NoFocus`,
    so asking it would report the two most important controls in the dialog as
    unreachable — measured, on the first run of the test that uses this.
    """
    return tuple(
        widget.focusPolicy()
        for widget in (
            dialog._roots,
            dialog._add,
            dialog._remove,
            dialog._poll,
            dialog._log,
            dialog._buttons.button(QDialogButtonBox.StandardButton.Ok),
            dialog._buttons.button(QDialogButtonBox.StandardButton.Cancel),
        )
    )
