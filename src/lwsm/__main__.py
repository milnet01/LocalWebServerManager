"""Entry point for the `lwsm` console script and `python -m lwsm`."""

from __future__ import annotations

import argparse

from lwsm import __version__, applog


def main(argv: list[str] | None = None) -> int:
    """Configure logging and report status. No GUI until P02."""
    parser = argparse.ArgumentParser(
        prog="lwsm",
        description=(
            "Find, start, stop and watch the local web servers your projects run."
        ),
    )
    parser.add_argument("--version", action="version", version=f"lwsm {__version__}")
    # Parses sys.argv[1:] when argv is None. This replaces a `"--version" in
    # args` membership test, which had no --help and silently accepted every
    # option it did not recognise — a typo'd flag looked honoured and returned 0.
    parser.parse_args(argv)

    try:
        log_path = applog.configure_logging()
    except OSError as exc:
        # A log we cannot write is worth a warning, not a crash. The 2026-08-06
        # hardening deliberately refuses several hostile filesystem states, so
        # without this branch each of them would kill the app on startup.
        applog.configure_stderr_logging()
        applog.get_logger(__name__).warning(
            "no application log (%s) — continuing without one", exc
        )
        log_path = None
    else:
        applog.get_logger(__name__).info("lwsm %s started", __version__)

    print(f"lwsm {__version__} — no interface yet (P02 builds it).")
    print(f"Logging to {log_path}" if log_path else "Not logging to a file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
