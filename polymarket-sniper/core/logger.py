"""Structured logging configuration."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def configure_logger(log_path: str | Path = "data/bot.log") -> None:
    """Configure loguru for JSON stdout and rotating file logs."""
    logger.remove()
    logger.add(sys.stdout, level="INFO", serialize=True, backtrace=False, diagnose=False)
    logger.add(
        str(log_path),
        level="DEBUG",
        rotation="50 MB",
        retention="14 days",
        enqueue=True,
        serialize=True,
        backtrace=False,
        diagnose=False,
    )


__all__ = ["logger", "configure_logger"]
