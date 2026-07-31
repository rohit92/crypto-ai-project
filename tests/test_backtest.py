"""
Tests for backtest.py — the historical strategy backtester.

Fully offline: the engine runs on a plain list of closing prices, so no network,
pandas, or API key is needed. A "scripted" strategy (fixed signal per bar) makes
cash/PnL exactly hand-computable; indicators and metrics are checked on known
inputs.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import backtest as bt  # noqa: E402


def scripted(signals):
    """A strategy that emits a predetermined signal at each bar index."""
    return lambda closes, i: signals[i]


class TestIndicators(unittest.TestCase):
    def test_sma_basic(self):
        self.assertEqual(bt.sma([1, 2, 3, 4], 2), 3.5)
        self.assertEqual(bt.sma([1, 2, 3, 4], 4), 2.5)

    def test_sma_insufficient_data_is_none(self):
        self.assertIsNone(bt.sma([1, 2], 3))

    def test_rsi_all_up_is_100(self):
        self.assertEqual(bt.rsi(list(range(1, 16)), 14), 100.0)

    def test_rsi_insufficient_data_is_none(self):
        self.assertIsNone(bt.rsi([1, 2, 3], 14))


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.closes = [100, 110, 105, 120]

    def test_single_round_trip_pnl(self):
        # buy@100, hold, sell@105 -> +5% on a $10k account, 1 winning trade.
        r = bt.run(self.closes, scripted([1, 0, -1, 0]), initial_cash=10_000, fee=0.0)
        self.assertEqual(r["total_return_pct"], 5.0)
        self.assertEqual(r["final_equity"], 10_500.0)
        self.assertEqual(r["num_trades"], 1)
        self.assertEqual(r["win_rate_pct"], 100.0)
        self.assertEqual(r["equity_curve"], [10_000.0, 11_000.0, 10_500.0, 10_500.0])

    def test_buy_hold_matches_price_appreciation(self):
        r = bt.run(self.closes, bt.buy_and_hold(), initial_cash=10_000, fee=0.0)
        self.assertEqual(r["total_return_pct"], 20.0)          # 100 -> 120
        self.assertEqual(r["total_return_pct"], r["buy_hold_return_pct"])
        self.assertEqual(r["num_trades"], 0)                   # never sells

    def test_fees_reduce_return(self):
        no_fee = bt.run(self.closes, scripted([1, 0, -1, 0]), 10_000, fee=0.0)
        with_fee = bt.run(self.closes, scripted([1, 0, -1, 0]), 10_000, fee=0.001)
        self.assertLess(with_fee["total_return_pct"], no_fee["total_return_pct"])

    def test_duplicate_buy_signal_does_not_double_position(self):
        # A second buy while already long is ignored (all-in, long-only).
        r = bt.run(self.closes, scripted([1, 1, -1, 0]), 10_000, fee=0.0)
        self.assertEqual(r["num_trades"], 1)
        self.assertEqual(r["total_return_pct"], 5.0)

    def test_open_position_marked_to_market_not_counted_as_trade(self):
        r = bt.run(self.closes, scripted([1, 0, 0, 0]), 10_000, fee=0.0)
        self.assertEqual(r["num_trades"], 0)                   # never closed
        self.assertEqual(r["final_equity"], 12_000.0)          # 100 units * 120

    def test_empty_prices_raise(self):
        with self.assertRaises(ValueError):
            bt.run([], bt.buy_and_hold())


class TestMetrics(unittest.TestCase):
    def test_max_drawdown_on_known_curve(self):
        # equity 100 -> 120 -> 90 -> 110 : worst DD = (120-90)/120 = 25%
        r = bt.run([100, 120, 90, 110], scripted([1, 0, 0, 0]), 100, fee=0.0)
        # equity mirrors price (all-in from bar 0), so DD is 25%.
        self.assertAlmostEqual(r["max_drawdown_pct"], 25.0, places=3)

    def test_report_renders(self):
        r = bt.run([100, 110, 120], bt.buy_and_hold(), fee=0.0)
        text = bt.format_report(r, label="demo")
        self.assertIn("Backtest demo", text)
        self.assertIn("Edge vs B&H", text)


class TestStrategies(unittest.TestCase):
    def test_sma_crossover_enters_on_upcross(self):
        # flat then rising: fast(2) crosses above slow(4) as the ramp begins.
        closes = [10, 10, 10, 10, 11, 13, 15, 17, 19, 21]
        r = bt.run(closes, bt.sma_crossover(fast=2, slow=4), fee=0.0)
        self.assertGreaterEqual(r["num_trades"] + (1 if r["final_equity"] else 0), 1)
        # It should have taken at least one long and beaten cash on this uptrend.
        self.assertGreater(r["total_return_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
