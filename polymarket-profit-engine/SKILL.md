---
name: polymarket-profit-engine
description: |
  Autonomous Polymarket 5-minute trading bot. Runs 12 battle plans
  across BTC, ETH, SOL, XRP simultaneously. 8 self-learning systems
  update every variable as the market moves. Covers every window
  systematically. Never trades stale or expired windows. Auto takes
  profit. Self-diagnoses losses. Never stops.

  TRIGGERS: start bot, stop bot, bot status, trading status,
  show plans, show performance, pause trading, resume trading,
  emergency stop, show positions, bot report, show trades,
  show bankroll, show signals, show regime, show coverage

metadata:
  openclaw:
    emoji: 🦞
    background: true
    persistent_memory: true
    telegram_control: true
    startup_command: "uv run python main.py"
    health_check_command: "uv run python scripts/health_check.py"
    requires:
      env:
        - POLYMARKET_PRIVATE_KEY
        - POLYMARKET_API_KEY
        - POLYMARKET_API_SECRET
        - POLYMARKET_API_PASSPHRASE
        - POLYMARKET_PROXY_ADDRESS
        - CHAINSTACK_NODE
        - PROXY_HOST
        - PROXY_PORT
        - PROXY_USER
        - PROXY_PASS
        - TELEGRAM_BOT_TOKEN
        - TELEGRAM_CHAT_ID
        - STARTING_BANKROLL
        - MIN_BET
        - PAPER_MODE
---
