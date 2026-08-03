"""Entry point for the `lwsm` console script and `python -m lwsm`."""

from __future__ import annotations

import sys

from lwsm import __version__, applog


def main(argv: list[str] | None = None) -> int:
    """Configure logging and report status. No GUI until P02."""
    args = sys.argv[1:] if argv is None else argv

    if "--version" in args:
        print(f"lwsm {__version__}")
        return 0

    log_path = applog.configure_logging()
    applog.get_logger(__name__).info("lwsm %s started", __version__)
    print(f"lwsm {__version__} — no interface yet (P02 builds it).")
    print(f"Logging to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
