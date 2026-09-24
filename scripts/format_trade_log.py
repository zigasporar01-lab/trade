"""Turns data/trade_log_<mode>.csv into a formatted, color-coded .xlsx you
can open directly in Excel — no delimiter/regional-settings issues, since
.xlsx isn't a plain-text format.

Usage:
    python scripts/format_trade_log.py                     # paper mode, default paths
    python scripts/format_trade_log.py --mode live
    python scripts/format_trade_log.py --input path/to/log.csv --output path/to/out.xlsx

Safe to re-run anytime — it always rebuilds the workbook fresh from the
current CSV, so it never goes stale relative to your trade history.

The same workbook can also be generated on demand from Telegram —
see the /export command in memebot/utils/telegram_commands.py.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from memebot.core.xlsx_export import build_workbook  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Format a memebot trade log CSV as a colored .xlsx")
    parser.add_argument("--mode", default="paper", help="paper | live (used for default file paths)")
    parser.add_argument("--input", type=Path, default=None, help="Path to the source CSV")
    parser.add_argument("--output", type=Path, default=None, help="Path to write the .xlsx to")
    args = parser.parse_args()

    input_path = args.input or (REPO_ROOT / "data" / f"trade_log_{args.mode}.csv")
    output_path = args.output or input_path.with_suffix(".xlsx")

    if not input_path.exists():
        raise SystemExit(f"No trade log found at {input_path} — has the bot been run yet?")

    with open(input_path, newline="") as f:
        rows = list(csv.DictReader(f))

    wb = build_workbook(rows)
    wb.save(output_path)
    print(f"Wrote {len(rows)} trade(s) to {output_path}")


if __name__ == "__main__":
    main()
