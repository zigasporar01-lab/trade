"""Permanent, append-only record of every closed trade, surviving restarts.

The in-memory Portfolio resets every time the process restarts (your laptop
sleeping, a crash, a manual stop) — it can only answer "how has this run
been doing," not "how has this bot been doing over the weeks I've been
testing it." This writes one CSV row per closed trade so that question has
a real answer, and so the file can be opened directly in Excel/Sheets.
"""

from __future__ import annotations

import csv
from pathlib import Path

from memebot.models import Position

FIELDNAMES = [
    "closed_at",
    "opened_at",
    "mode",
    "symbol",
    "token_address",
    "entry_price",
    "close_price",
    "size_sol",
    "pnl_sol",
    "pnl_pct",
    "close_reason",
]


class TradeLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with open(self.path, "w", newline="") as f:
                csv.DictWriter(f, fieldnames=FIELDNAMES).writeheader()

    def record(self, position: Position, mode: str) -> None:
        with open(self.path, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writerow(
                {
                    "closed_at": position.closed_at.isoformat() if position.closed_at else "",
                    "opened_at": position.opened_at.isoformat(),
                    "mode": mode,
                    "symbol": position.symbol,
                    "token_address": position.token_address,
                    "entry_price": position.entry_price,
                    "close_price": position.close_price,
                    "size_sol": position.size_sol,
                    "pnl_sol": position.pnl_sol,
                    "pnl_pct": position.pnl_pct,
                    "close_reason": position.close_reason,
                }
            )

    def load_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        with open(self.path, newline="") as f:
            return list(csv.DictReader(f))

    def summary(self) -> dict:
        rows = self.load_all()
        pnl_values = [float(r["pnl_sol"]) for r in rows if r.get("pnl_sol")]
        wins = sum(1 for v in pnl_values if v > 0)
        losses = sum(1 for v in pnl_values if v <= 0)
        return {
            "total_trades": len(rows),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / len(pnl_values)) if pnl_values else None,
            "total_pnl_sol": sum(pnl_values),
            "best_trade_sol": max(pnl_values) if pnl_values else None,
            "worst_trade_sol": min(pnl_values) if pnl_values else None,
        }
