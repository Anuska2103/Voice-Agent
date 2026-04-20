"""
Shared logging utilities for terminal-friendly application logs.

- Prints structured logs to stdout.
- Suppresses noisy PyMongo/Motor topology debug logs.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def setup_logging() -> None:
    """Configure root logging once for the whole process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root_logger.addHandler(handler)

    # Suppress noisy driver internals while keeping warnings/errors.
    for name in (
        "pymongo",
        "pymongo.topology",
        "pymongo.connection",
        "pymongo.serverSelection",
        "pymongo.command",
        "motor",
    ):
        logging.getLogger(name).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a module logger after ensuring logging is configured."""
    setup_logging()
    return logging.getLogger(name)
