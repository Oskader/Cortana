# AGENTS.md — Cortana Trading Bot

## Run Commands

```bash
# Paper mode (demo account)
python main.py
# or
make run-paper

# Live mode (real money — requires confirmation)
TRADING_MODE=live python main.py

# Tests
python -m pytest tests/ -v --asyncio-mode=auto

# Lint
make lint

# Docker
docker-compose up -d
docker-compose logs -f

# Logs
tail -f logs/bot.log

# Backup DB
make backup-db
```

## Architecture

- **Entry point**: `main.py` — single-instance lock via `portalocker` prevents parallel runs (`cortana_bot.lock`)
- **Engine**: `trading_bot/core/engine.py` — `TradingEngine` orchestrates all modules
- **Key modules**: `config/`, `core/`, `market/`, `execution/`, `risk/`, `brain/`, `telegram/`, `utils/`
- **DB**: SQLite at `data/trading_bot.db` via SQLAlchemy (`trading_bot/utils/db.py`)
- **Settings**: Pydantic settings from `.env` — invalid env vars cause silent/hard failures on startup

## Environment

- **Python**: 3.10+
- **Env file**: `.env` (copy from `.env.example`); API keys for Alpaca, Groq, Telegram required; `GROQ_MODEL=llama-3.3-70b-versatile`
- **No `.env`**: `make lint` fails; `from trading_bot.config.settings import settings` throws
- **Windows**: `asyncio.WindowsSelectorEventLoopPolicy()` auto-set at entry point

## Trading Logic

- **Fractional shares** via Alpaca: bot verifies asset is `fractionable=true` before ordering
- **SMC + AI**: `groq_agent.py` scores trades; `GROQ_MIN_SCORE=6.0` threshold; VIX>25 blocks all trades
- **PDT Compliance**: round-trips counted over last 5 business days; halts if equity < $25,000
- **Risk guards**: `-15%` drawdown = PAUSE; `-25%` = HALT; `MAX_DAILY_LOSS_PCT` per day

## Alpaca Integration (Verified Against Official Docs)

### Order Types (Correct Implementation)
- **Notional orders**: `MarketOrderRequest(symbol, notional=$, side, time_in_force=DAY)` — correct for fractional shares
- **Bracket orders**: Supported with `OrderClass.BRACKET` + `StopLossRequest` + `TakeProfitRequest` — for whole shares only
- **time_in_force**: MUST be `DAY` for fractional orders (Alpaca requirement)

### Fractional Shares (Verified)
- Minimum notional: `$1.00` USD (Alpaca requirement)
- Verify with `get_asset(symbol)` checking `fractionable=true` before ordering
- Not all stocks support fractional; bot skips non-fractionable

### Account Verification (Verified)
- Engine verifies `account.status == "ACTIVE"` at startup
- Checks `account.trading_blocked == false`
- Uses `TradingClient(paper=is_paper)` for correct API endpoint

### Paper vs Live Trading
- `TRADING_MODE=paper` → uses paper API, `TradingClient(paper=True)`
- `TRADING_MODE=live` → uses live API, `TradingClient(paper=False)`
- Paper account has `$100k` default balance (reset in dashboard)

### Key Fixes Made

1. **GROQ_MIN_SCORE**: was missing, now defaults to 6.0 (was 7.0, too strict)
2. **GROQ_MIN_CONFIDENCE**: lowered from 0.72 to 0.60 to allow more trades
3. **Fractional verification**: engine calls `get_asset(symbol)` before ordering
4. **Account verification**: verifies account status is ACTIVE at startup
5. **Minimum notional**: enforces $1.00 minimum (Alpaca requirement)
6. **Order status check**: verifies order wasn't rejected/expired after submission
7. **PDT protection**: Paper trading simulates PDT rule (4th day trade blocked under $25k)

## Testing

- Use `--asyncio-mode=auto` flag (required for `pytest-asyncio`)
- Fixtures: `tests/conftest.py`
- Run single test: `python -m pytest tests/test_signal_scorer.py -v`

## Docker

- `Dockerfile` + `docker-compose.yml` for deployment
- Railway config: `railway.json`
- `TRADING_MODE` set via env var at runtime, not baked into image