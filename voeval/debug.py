"""CLI debug logging helpers aligned with evo-style flags."""

from __future__ import annotations

import getpass
import logging
import platform
import sys
from pathlib import Path

CONSOLE_FORMAT = "%(message)s"
DEBUG_FORMAT = "[%(levelname)s][%(asctime)s][%(module)s.%(funcName)s():%(lineno)s]\n%(message)s"


def configure_logging(
    *,
    verbose: bool = False,
    silent: bool = False,
    debug: bool = False,
    logfile: str | Path | None = None,
) -> logging.Logger:
    """Configure the package logger for CLI runs.

    This intentionally follows evo's public behavior: ``--debug`` and ``-v`` make
    console logs verbose, ``--silent`` hides normal summaries, and ``--logfile``
    always receives DEBUG-level details.
    """

    logger = logging.getLogger("voeval")
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console_level = logging.DEBUG if (debug or verbose) else (logging.WARNING if silent else logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level)
    console_handler.setFormatter(logging.Formatter(DEBUG_FORMAT if debug else CONSOLE_FORMAT))
    logger.addHandler(console_handler)

    if logfile is not None:
        log_path = Path(logfile).expanduser()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(DEBUG_FORMAT))
        logger.addHandler(file_handler)

    logger.setLevel(logging.DEBUG if (debug or verbose or logfile is not None) else console_level)
    if debug:
        logger.debug(system_info_text())
    return logger


def system_info_text() -> str:
    """Return a compact system info block for debug logs."""

    return "\n".join(
        [
            "System info:",
            f"Python {sys.version.split()[0]}",
            platform.platform(),
            f"{getpass.getuser()}@{platform.node()}",
        ]
    )
