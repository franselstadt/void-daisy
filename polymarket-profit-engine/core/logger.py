"""Structured logger configuration."""

from __future__ import annotations

import os
import sys

from loguru import logger


def setup_logging() -> None:
    os.makedirs('logs', exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, format='{time:HH:mm:ss} | {level} | {message}', level='INFO')
    logger.add('logs/bot_{time:YYYY-MM-DD}.log', rotation='1 day', retention='7 days', level='DEBUG')
    logger.add('data/bot.log', rotation='25 MB', retention='14 days', serialize=True, level='DEBUG')
