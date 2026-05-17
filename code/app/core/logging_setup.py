"""Centralized logging config. Imported once at startup."""

from __future__ import annotations

import logging
import os
import sys


def setup_logging(level: str | None = None) -> None:
    level = level or os.environ.get("SAMPLER_LOG", "INFO")
    fmt = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        stream=sys.stderr,
    )
    # Quiet noisy libs
    for noisy in ("numba", "matplotlib", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
