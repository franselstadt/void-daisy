"""One-time Polymarket approval script."""

from __future__ import annotations

import argparse


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['approve'])
    args = p.parse_args()
    if args.action == 'approve':
        print('Approval placeholder: integrate py-clob-client approve flow.')


if __name__ == '__main__':
    main()
