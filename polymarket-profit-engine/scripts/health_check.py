"""OpenClaw health check executed every 60 seconds as a separate process.

Since this runs independently, it checks file-based indicators rather
than in-memory state which only exists in the main bot process.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def main() -> int:
    os.chdir(os.path.dirname(os.path.dirname(__file__)) or '.')

    log_path = Path('data/bot.log')
    if log_path.exists():
        age = time.time() - log_path.stat().st_mtime
        if age > 120:
            print(f'UNHEALTHY: log file stale ({age:.0f}s)')
            return 1
    else:
        print('UNHEALTHY: no log file found')
        return 1

    db_path = Path('data/trades.db')
    if not db_path.exists():
        print('UNHEALTHY: trades.db missing')
        return 1

    config_path = Path('data/config.json')
    if not config_path.exists():
        print('UNHEALTHY: config.json missing')
        return 1

    print('HEALTHY')
    return 0


if __name__ == '__main__':
    sys.exit(main())
