"""Structured logger configuration."""

from __future__ import annotations

import sys
from loguru import logger


def setup_logging() -> None:
    logger.remove()
    logger.add(sys.stdout, level="INFO", serialize=True, backtrace=False, diagnose=False)
    logger.add("data/bot.log", level="DEBUG", rotation="25 MB", retention="14 days", serialize=True)
