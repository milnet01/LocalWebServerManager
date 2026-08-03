"""LocalWebServerManager — find, start, stop and watch local dev servers.

Layering, enforced by import and by `docs/standards/coding.md § O1`: this
package's core modules may import `QtCore` but never `QtWidgets`, so every one
of them is testable without a display.
"""

from __future__ import annotations

__version__ = "0.0.0"
