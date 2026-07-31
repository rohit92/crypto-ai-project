"""
backtest.py — a vectorised backtesting engine for the paper-trading terminal.

The dashboard trades live; this module lets you test a strategy over *historical*
candles first and get hard numbers — total return vs buy-and-hold, Sharpe, max
drawdown, trade count, and win rate — before risking (paper) money on it.

The engine is long-only and self-contained: it runs on a plain list of closing
prices, so the core and its tests need no network, no pandas, and no API key. A
thin adapter (`fetch_closes`) pulls real Binance candles via the existing
``BinanceDataHandler`` for a live backtest from the CLI.

    python backtest.py --symbol BTC/USDT:USDT --timeframe 1h --strategy sma
"""

from __future__ import annotations

import argparse
import math
from typing import Callable, Dict, List, Optional, Sequence

# A strategy maps (closes so far, current index) -> +1 buy/long, -1 exit, 0 hold.
Strategy = Callable[[Sequence[float], int], int]


# --------------------------------------------------------------------------- #
#  Indicators
# --------------------------------------------------------------------------- #

def sma(values: Sequence[float], period: int) -> Optional[float]:
    """Simple moving average of the last ``period`` values, or None if too few."""

    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def rsi(values: Sequence[float], period: int = 14) -> Optional[float]:
    """Wilder-style RSI over the last ``period`` deltas (None if too few)."""

    if len(values) <= period:
        return None
    gains, losses = 0.0, 0.0
    for prev, cur in zip(values[-period - 1:-1], values[-period:]):
        change = cur - prev
        if change >= 0:
            gains += change
        else:
            losses -= change
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# --------------------------------------------------------------------------- #
#  Strategies
# --------------------------------------------------------------------------- #

def buy_and_hold() -> Strategy:
    """Buy on the first bar, hold forever — the benchmark every strategy must beat."""

    def strat(closes: Sequence[float], i: int) -> int:
        return 1 if i == 0 else 0
    return strat


def sma_crossover(fast: int = 10, slow: int = 30) -> Strategy:
    """Go long when the fast SMA crosses above the slow SMA; exit on cross down."""

    def strat(closes: Sequence[float], i: int) -> int:
        if i < slow:
            return 0
        f_now, s_now = sma(closes[: i + 1], fast), sma(closes[: i + 1], slow)
        f_prev, s_prev = sma(closes[:i], fast), sma(closes[:i], slow)
        if None in (f_now, s_now, f_prev, s_prev):
            return 0
        if f_prev <= s_prev and f_now > s_now:
            return 1
        if f_prev >= s_prev and f_now < s_now:
            return -1
        return 0
    return strat


def rsi_reversion(period: int = 14, low: float = 30.0, high: float = 70.0) -> Strategy:
    """Mean reversion: buy when RSI is oversold, exit when overbought.

    Mirrors the signal logic already used in the live dashboard.
    """

    def strat(closes: Sequence[float], i: int) -> int:
        value = rsi(closes[: i + 1], period)
        if value is None:
            return 0
        if value < low:
            return 1
        if value > high:
            return -1
        return 0
    return strat


STRATEGIES = {
    "hold": buy_and_hold,
    "sma": sma_crossover,
    "rsi": rsi_reversion,
}


# --------------------------------------------------------------------------- #
#  Metrics
# --------------------------------------------------------------------------- #

def _sharpe(returns: Sequence[float]) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    std = math.sqrt(var)
    return 0.0 if std == 0 else mean / std


def _max_drawdown(curve: Sequence[float]) -> float:
    peak, worst = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            worst = max(worst, (peak - v) / peak)
    return worst


# --------------------------------------------------------------------------- #
#  Engine
# --------------------------------------------------------------------------- #

def run(
    closes: Sequence[float],
    strategy: Strategy,
    initial_cash: float = 10_000.0,
    fee: float = 0.001,
) -> Dict:
    """Backtest ``strategy`` over ``closes`` (long-only, all-in sizing).

    Returns equity curve, closed trades, and summary metrics. A position still
    open at the end is marked to market in the equity curve but not counted as a
    closed trade.
    """

    if not closes:
        raise ValueError("need at least one closing price")

    cash = float(initial_cash)
    units = 0.0
    entry_price = 0.0
    equity_curve: List[float] = []
    trades: List[Dict] = []

    for i, price in enumerate(closes):
        signal = strategy(closes, i)
        if signal == 1 and units == 0.0:          # enter long, all-in
            units = (cash * (1.0 - fee)) / price
            entry_price = price
            cash = 0.0
        elif signal == -1 and units > 0.0:        # exit to cash
            cash = units * price * (1.0 - fee)
            trades.append({
                "entry": entry_price,
                "exit": price,
                "return_pct": round((price / entry_price - 1.0) * 100.0, 4),
            })
            units = 0.0
        equity_curve.append(cash + units * price)

    # Per-bar equity returns for Sharpe.
    bar_returns = [
        equity_curve[i] / equity_curve[i - 1] - 1.0
        for i in range(1, len(equity_curve))
        if equity_curve[i - 1] > 0
    ]
    wins = [t for t in trades if t["return_pct"] > 0]
    bh = (closes[-1] / closes[0] - 1.0) * 100.0

    return {
        "bars": len(closes),
        "initial_cash": initial_cash,
        "final_equity": round(equity_curve[-1], 2),
        "total_return_pct": round((equity_curve[-1] / initial_cash - 1.0) * 100.0, 3),
        "buy_hold_return_pct": round(bh, 3),
        "sharpe_per_bar": round(_sharpe(bar_returns), 4),
        "max_drawdown_pct": round(_max_drawdown(equity_curve) * 100.0, 3),
        "num_trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 2) if trades else 0.0,
        "equity_curve": equity_curve,
        "trades": trades,
    }


def format_report(result: Dict, label: str = "") -> str:
    edge = result["total_return_pct"] - result["buy_hold_return_pct"]
    return "\n".join([
        f"Backtest {label}".rstrip(),
        "=" * 40,
        f"  Bars               {result['bars']}",
        f"  Trades             {result['num_trades']}",
        f"  Win rate           {result['win_rate_pct']}%",
        f"  Total return       {result['total_return_pct']}%",
        f"  Buy & hold         {result['buy_hold_return_pct']}%",
        f"  Edge vs B&H        {edge:+.3f}%",
        f"  Sharpe (per bar)   {result['sharpe_per_bar']}",
        f"  Max drawdown       {result['max_drawdown_pct']}%",
        f"  Final equity       {result['final_equity']}",
    ])


# --------------------------------------------------------------------------- #
#  Live data adapter + CLI
# --------------------------------------------------------------------------- #

def fetch_closes(symbol: str, timeframe: str = "1h", limit: int = 500) -> List[float]:
    """Pull real Binance closing prices via the existing data handler."""

    from backend import BinanceDataHandler  # lazy: needs ccxt + network
    df = BinanceDataHandler().fetch_market_data(symbol, timeframe=timeframe, limit=limit)
    if df.empty:
        raise SystemExit(f"no data for {symbol} {timeframe}")
    return [float(x) for x in df["close"].tolist()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Backtest a strategy on Binance data.")
    parser.add_argument("--symbol", default="BTC/USDT:USDT")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--strategy", choices=sorted(STRATEGIES), default="sma")
    parser.add_argument("--cash", type=float, default=10_000.0)
    parser.add_argument("--fee", type=float, default=0.001)
    args = parser.parse_args(argv)

    closes = fetch_closes(args.symbol, args.timeframe, args.limit)
    result = run(closes, STRATEGIES[args.strategy](), initial_cash=args.cash, fee=args.fee)
    print(format_report(result, label=f"{args.symbol} {args.timeframe} [{args.strategy}]"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
