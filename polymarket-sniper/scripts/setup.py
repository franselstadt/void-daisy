"""One-time setup and approvals for Polymarket."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["approve"], help="Setup action")
    args = parser.parse_args()
    if args.action == "approve":
        print("Approval workflow placeholder: integrate py-clob-client approvals here.")


if __name__ == "__main__":
    main()
