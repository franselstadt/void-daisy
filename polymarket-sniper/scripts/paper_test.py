"""Simple paper-mode smoke runner."""

from __future__ import annotations

import asyncio
import os


async def main() -> None:
    os.environ["PAPER_MODE"] = "true"
    print("Paper test scaffold ready. Run main.py for full simulation.")
    await asyncio.sleep(0)


if __name__ == "__main__":
    asyncio.run(main())
