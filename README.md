# Crypto AI Trading Terminal

A Streamlit dashboard for **paper trading** crypto futures, with live Binance
market data and AI-assisted market commentary from Google Gemini. No real funds
are ever traded — positions and balance are simulated in a local SQLite database.

## Features

- **Live market data** — Binance USDT-perpetual futures via [ccxt](https://github.com/ccxt/ccxt)
  (prices, OHLCV candles, symbol list).
- **AI market analysis** — `analyze_market_with_ai()` sends recent candles to
  Gemini for a short read on the setup.
- **Paper trading wallet** — `PaperTradingWallet` tracks balance and open
  positions in `trading_data.db` (starting balance $10,000); `execute_trade()`
  simulates buys/sells.
- **Interactive UI** — asset picker, timeframe selector, and Plotly charts.

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Provide your Gemini API key via the environment (the key is **never** stored in
source):

```bash
cp .env.example .env
# then edit .env and set GEMINI_API_KEY=...
```

Get a key at <https://aistudio.google.com/app/apikey>.

## Run

```bash
streamlit run dashboard.py
```

Helper scripts:

- `python check_models.py` — list the Gemini models available to your key.
- `python debug.py` — quick connectivity check to the Gemini API.

## Backtesting

Before trading a strategy live, test it over historical candles and get hard
numbers — return vs buy-and-hold, Sharpe, max drawdown, trade count, win rate:

```bash
python backtest.py --symbol BTC/USDT:USDT --timeframe 1h --strategy sma
```

```text
Backtest BTC/USDT:USDT 1h [sma]
  Trades             14
  Win rate           57.14%
  Total return       8.30%
  Buy & hold         5.10%
  Edge vs B&H        +3.200%
  Sharpe (per bar)   0.041
  Max drawdown       6.20%
```

Built-in strategies: `hold` (benchmark), `sma` (SMA crossover), `rsi` (the same
oversold/overbought logic the dashboard uses). The engine is long-only and runs
on a plain list of closing prices, so it's fully unit-tested offline with no
network or API key (`tests/test_backtest.py`). *(The figures above are
illustrative formatting — real numbers depend on the window you pull.)*

## Layout

| File | Purpose |
|------|---------|
| `dashboard.py` | Streamlit UI (the app entry point) |
| `backend.py` | `BinanceDataHandler` + `PaperTradingWallet` |
| `backtest.py` | Historical strategy backtester (offline-testable engine + CLI) |
| `check_models.py`, `debug.py` | Gemini connectivity helpers |
| `trading_data.db` | local SQLite paper-trading state (gitignored) |

## Security note

API keys are read from the environment only. `.env` and `*.db` are gitignored.
If a key was ever committed or shared, **rotate it** in Google AI Studio.

> ⚠️ This is an educational paper-trading tool, not financial advice. It does
> not place real orders.
