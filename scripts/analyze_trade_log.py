"""Reads the trade log and prints plain-English, actionable suggestions —
semi-automates the "review the log and notice patterns" workflow. Does not
change any config itself; you still decide whether to act on a suggestion.

Usage:
    python scripts/analyze_trade_log.py                # paper mode
    python scripts/analyze_trade_log.py --mode live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from memebot.core.trade_analysis import analyze  # noqa: E402
from memebot.core.trade_log import TradeLog  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a memebot trade log for patterns")
    parser.add_argument("--mode", default="paper", help="paper | live")
    args = parser.parse_args()

    path = REPO_ROOT / "data" / f"trade_log_{args.mode}.csv"
    if not path.exists():
        raise SystemExit(f"No trade log found at {path} — has the bot closed any trades yet?")

    rows = TradeLog(path).load_all()
    result = analyze(rows)

    o = result["overall"]
    print(f"=== Trade log analysis ({args.mode}) ===\n")
    print(f"Total trades: {o['total_trades']}")
    if o["win_rate"] is not None:
        print(f"Win rate: {o['win_rate'] * 100:.0f}% ({o['wins']}W / {o['losses']}L)")
    print(f"Total PnL: {o['total_pnl_sol']:+.5f} SOL\n")

    if result["by_reason"]:
        print("By exit reason:")
        for reason, stats in sorted(result["by_reason"].items(), key=lambda kv: -kv[1]["count"]):
            print(f"  {reason}: {stats['count']} trades, {stats['total_pnl_sol']:+.5f} SOL total")
        print()

    print("Suggestions:")
    for s in result["suggestions"]:
        print(f"  - {s}")


if __name__ == "__main__":
    main()
