"""Reading the window-level message, for the tests that check one.

Not named `test_*`, so pytest imports it rather than collecting it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from lwsm.mainwindow import MainWindow


def message_of(window: MainWindow) -> str:
    """The window-level message the user can see, or "" when none is shown.

    It is the message row in the notice strip (LWSM-1345, LWSM-1579), so a
    hidden row reads as no message even if it still holds the last text.
    `isVisibleTo`, not `isVisible`, so it also answers for a window not yet
    on screen.
    """
    return window._banner_text.text() if window._banner.isVisibleTo(window) else ""
