"""Backtests the 4h strategy against real historical price data.

IMPORTANT — read this before trusting the numbers it prints:
  This validates ONLY the technical strategy (trend/breakout/RSI/ATR-stop/
  R:R-target/trailing-stop/time-exit). It CANNOT validate the on-chain or
  social safety checks, since RugCheck/GoPlus only expose a token's
  *current* state, not a historical snapshot. It also only sees tokens
  that still exist today (survivorship bias) — tokens that rugged and
  vanished aren't in this data. Treat results as an upper bound on real
  performance, not a prediction of it. See memebot/backtest/engine.py for
  the full list of caveats.

Usage:
    python scripts/run_backtest.py --pool <geckoterminal-pool-address> [--pool <another>] ...
    python scripts/run_backtest.py --pool <address> --symbol BONK --months 3

Finding a pool address: open the token on dexscreener.com, the address in
the URL after the chain name (e.g. dexscreener.com/solana/<THIS PART>) is
the pool address GeckoTerminal also uses. Pick tokens with a long, liquid
history (established memecoins) — a token that launched last week won't
give the strategy enough history to test meaningfully.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from memebot.backtest.engine import run_backtest  # noqa: E402
from memebot.config import load_settings  # noqa: E402
from memebot.core.xlsx_export import build_backtest_workbook  # noqa: E402
from memebot.data.geckoterminal import GeckoTerminalClient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the 4h strategy against historical OHLCV data")
    parser.add_argument("--pool", action="append", required=True, help="GeckoTerminal/DexScreener pool address (repeatable)")
    parser.add_argument("--symbol", action="append", default=None, help="Label for each --pool, same order (optional)")
    parser.add_argument("--network", default="solana")
    parser.add_argument("--months", type=float, default=3.0, help="How much history to pull, in months")
    parser.add_argument("--output", type=Path, default=None, help="Path to write the .xlsx report")
    args = parser.parse_args()

    settings = load_settings()
    symbols = args.symbol or [f"POOL_{i + 1}" for i in range(len(args.pool))]
    if len(symbols) != len(args.pool):
        raise SystemExit("--symbol must be given once per --pool, in the same order, or not at all.")

    aggregate_hours = settings.strategy.ohlcv_aggregate_hours
    candles_needed = int(args.months * 30 * 24 / aggregate_hours)

    client = GeckoTerminalClient()
    results = []
    try:
        for symbol, pool in zip(symbols, args.pool):
            print(f"Fetching ~{args.months:.1f} months of {aggregate_hours}h candles for {symbol} ({pool})...")
            candles = client.get_ohlcv_history(
                network=args.network,
                pool_address=pool,
                aggregate_hours=aggregate_hours,
                total_candles=candles_needed,
            )
            print(f"  got {len(candles)} candles")
            if len(candles) < 30:
                print(f"  skipping {symbol}: not enough history for a meaningful backtest")
                continue

            result = run_backtest(candles, symbol, settings.strategy, settings.exits, settings.trading)
            results.append(result)

            s = result.summary
            win_rate = f"{s['win_rate'] * 100:.0f}%" if s["win_rate"] is not None else "n/a"
            print(
                f"  {symbol}: {s['total_trades']} trades, {win_rate} win rate, "
                f"{s['total_pnl_sol']:+.5f} SOL total, {s['max_drawdown_pct'] * 100:.1f}% max drawdown"
            )
    finally:
        client.close()

    if not results:
        print("\nNo symbols had enough history to backtest.")
        return

    output_path = args.output or (REPO_ROOT / "data" / "backtest_report.xlsx")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb = build_backtest_workbook(results)
    wb.save(output_path)
    print(f"\nWrote report to {output_path}")
    print(
        "\nReminder: this only tested the technical strategy, not the rug-pull "
        "safety checks, and only on tokens that still exist today. See the "
        "module docstring in memebot/backtest/engine.py for the full caveats."
    )


if __name__ == "__main__":
    main()
