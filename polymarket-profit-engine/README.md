# Polymarket Profit Engine

OpenClaw-native autonomous Polymarket skill.

## Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd polymarket-profit-engine
uv sync
```

## Configure

```bash
cp .env.example .env
```

## Run (paper)

```bash
PAPER_MODE=true uv run python main.py
```

## OpenClaw

- install skill from ./polymarket-profit-engine
- start polymarket bot
