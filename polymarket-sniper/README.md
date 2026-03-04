# Polymarket Sniper

Autonomous, event-driven Polymarket 5-minute sniper bot for BTC/ETH/SOL/XRP.

## Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd polymarket-sniper && uv sync
```

## Configure

```bash
cp .env.example .env
# Fill in all values in .env
```

## One-time Polymarket approval (first time only)

```bash
uv run python scripts/setup.py approve
```

## Run paper mode first — minimum 24 hours

```bash
PAPER_MODE=true uv run python main.py
```

Check paper results via Telegram: `/performance`
When win rate > 60% consistently: go live.

## Go live

```bash
PAPER_MODE=false uv run python main.py
```

## Install as OpenClaw skill

In OpenClaw: `install skill from ./polymarket-sniper`
Start via OpenClaw: `start polymarket sniper`

## Telegram commands

`/status /bankroll /trades /signals /performance /pause /resume /emergency_stop /degradation /config`

## Safety notes

- This software is provided as-is for research and automation.
- Run in paper mode before any live capital.
- Never run with funds you cannot afford to lose.
