"""The first-run confirmation (LWSM-1008).

UI layer — imports QtWidgets, so no core module may import it back
(`docs/standards/coding-overrides.md § O1`, enforced by `tests/test_layering.py`).

With no `projects.json` yet, the first scan's result is shown here before
anything is written (`design.md § Data flow`, LWSM-1131 § 4.4). Settled with
the user on 2026-10-02: every project found is listed with a tick box, ticked;
Save stores the ticked ones, Not now stores nothing and the next start asks
again. Below them, the scan's own reasons — folders not added, files not read —
one per line, because a project the scan missed is otherwise invisible. Only
real folders are listed there (user, 2026-10-02, LWSM-1383): plain files and
dot-folders buried the few that mattered, and both still reach the log.

**The dialog owns no I/O**, for `SettingsDialog`'s reason: it is handed records
and returns records, and the write stays in `MainWindow._apply_merge`, behind
the one write gate.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, QEvent, QLocale, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from lwsm.mainwindow import MIN_TARGET_PX, _filled
from lwsm.registry import ProjectRecord
from lwsm.scanner import MINOR_TAIL

# Every user-visible string here goes through the one context "FirstRunDialog",
# repeated as a literal because `pyside6-lupdate` skips a call whose context is
# not one — see mainwindow.py's note (LWSM-1304).


def _launcher(record: ProjectRecord) -> str:
    """What starts the project, as the user would type it."""
    if record.unit:
        return record.unit
    return " ".join(record.argv)


def worth_showing(reason: str) -> bool:
    """Whether one scan reason belongs in the dialog's "Not added" list.

    Read from the reason's wording, because `ScanResult.skipped` is strings:
    every per-entry reason opens with the entry's `repr`, so a dot-name opens
    `'.` or `".`. The filter lives here, not in the scanner, because the merge
    and the log read the scanner's reasons whole. `test_firstrun.py` runs the
    real scanner so a reworded reason fails there rather than reappearing here.
    """
    if reason.endswith(": is not a directory"):
        return False
    # The tail of the scanner's second budget, which holds only lines this
    # filter hides (LWSM-1384).
    if reason.endswith(MINOR_TAIL.split("{count}", 1)[1]):
        return False
    return not reason.startswith(("'.", '".'))


def describe(record: ProjectRecord) -> str:
    """One project's line: name, what starts it, and its port."""
    if record.port is None:
        return _filled(
            QCoreApplication.translate("FirstRunDialog", "%1 — %2, port not found"),
            record.name,
            _launcher(record),
        )
    return _filled(
        QCoreApplication.translate("FirstRunDialog", "%1 — %2, port %3"),
        record.name,
        _launcher(record),
        str(record.port),
    )


class FirstRunDialog(QDialog):
    """The projects a first scan found, each ticked, plus what it skipped."""

    def __init__(
        self,
        records: Sequence[ProjectRecord],
        skipped: Sequence[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setModal(True)
        self._records = list(records)

        self._intro = QLabel()
        self._intro.setWordWrap(True)

        self._boxes: list[QCheckBox] = []
        body = QWidget()
        column = QVBoxLayout(body)
        for _ in self._records:
            # Its text is set in `_retranslate`, with every other string.
            box = QCheckBox()
            box.setChecked(True)
            box.setMinimumHeight(MIN_TARGET_PX)
            box.toggled.connect(self._update_count)
            column.addWidget(box)
            self._boxes.append(box)

        self._skipped_title = QLabel()
        # Bold, so the two groups read apart at a glance; the system font's
        # own face and size are kept.
        heading = self._skipped_title.font()
        heading.setBold(True)
        self._skipped_title.setFont(heading)
        skipped = [reason for reason in skipped if worth_showing(reason)]
        self._skipped = QLabel("\n".join(skipped))
        # Plain and selectable, as `MainWindow.show_load_error` does: these
        # carry folder names from somebody else's tree.
        self._skipped.setTextFormat(Qt.TextFormat.PlainText)
        self._skipped.setWordWrap(True)
        self._skipped.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        column.addWidget(self._skipped_title)
        column.addWidget(self._skipped)
        self._skipped_title.setVisible(bool(skipped))
        self._skipped.setVisible(bool(skipped))
        column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)

        self._count = QLabel()
        self._buttons = QDialogButtonBox()
        self._save = QPushButton()
        self._later = QPushButton()
        self._buttons.addButton(self._save, QDialogButtonBox.ButtonRole.AcceptRole)
        self._buttons.addButton(self._later, QDialogButtonBox.ButtonRole.RejectRole)
        for button in (self._save, self._later):
            button.setMinimumHeight(MIN_TARGET_PX)
            button.setMinimumWidth(MIN_TARGET_PX)
        self._save.setDefault(True)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._intro)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._count)
        layout.addWidget(self._buttons)

        self._retranslate()

    def _retranslate(self) -> None:
        """Every user-visible string, in one method (`§ O8` clause 1)."""
        self.setWindowTitle(
            QCoreApplication.translate("FirstRunDialog", "Projects found")
        )
        self._intro.setText(
            QCoreApplication.translate(
                "FirstRunDialog",
                "Untick any project you do not want. Nothing is saved until "
                "you press Save.",
            )
            if self._records
            else QCoreApplication.translate(
                "FirstRunDialog",
                "No projects were found. Save keeps an empty list, so the next "
                "start does not scan again; Rescan looks again at any time.",
            )
        )
        self._skipped_title.setText(
            QCoreApplication.translate(
                "FirstRunDialog", "Not added, or not fully read:"
            )
        )
        for record, box in zip(self._records, self._boxes, strict=True):
            # `&` doubled: a check box reads a lone one as a keyboard shortcut,
            # and a folder name is not the place for one. Here rather than at
            # construction, so a language change reaches it (L09-L2).
            box.setText(describe(record).replace("&", "&&"))
        self._save.setText(QCoreApplication.translate("FirstRunDialog", "&Save"))
        self._later.setText(QCoreApplication.translate("FirstRunDialog", "&Not now"))
        self._update_count()

    def _update_count(self) -> None:
        self._count.setText(
            _filled(
                QCoreApplication.translate("FirstRunDialog", "Ticked: %1 of %2"),
                # The locale's digits, as the window's numbers are (L09-L1).
                QLocale().toString(len(self.chosen())),
                QLocale().toString(len(self._records)),
            )
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self._retranslate()
        super().changeEvent(event)

    def chosen(self) -> list[ProjectRecord]:
        """The ticked records, in the order they were listed."""
        return [
            record
            for record, box in zip(self._records, self._boxes, strict=True)
            if box.isChecked()
        ]


def ask_first_run(
    records: Sequence[ProjectRecord], skipped: Sequence[str], parent: QWidget
) -> list[ProjectRecord] | None:
    """Show the dialog; the ticked records on Save, `None` on Not now."""
    dialog = FirstRunDialog(records, skipped, parent)
    # `deleteLater` after the read, for `open_settings`' reason (LWSM-1276).
    try:
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.chosen()
    finally:
        dialog.deleteLater()
