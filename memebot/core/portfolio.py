"""Tracks open/closed positions and running PnL. Not persisted to disk by
default (state resets on restart) — see README for the note on adding
persistence before running unattended for long periods.
"""

from __future__ import annotations

from datetime import datetime

import structlog

from memebot.models import Position

log = structlog.get_logger(__name__)


class Portfolio:
    def __init__(self) -> None:
        self.open_positions: dict[str, Position] = {}
        self.closed_positions: list[Position] = []

    @property
    def open_capital_sol(self) -> float:
        return sum(p.size_sol for p in self.open_positions.values())

    @property
    def open_count(self) -> int:
        return len(self.open_positions)

    def has_open_position(self, token_address: str) -> bool:
        return token_address in self.open_positions

    def open_position(self, position: Position) -> None:
        self.open_positions[position.token_address] = position
        log.info(
            "portfolio.position_opened",
            token=position.token_address,
            symbol=position.symbol,
            entry_price=position.entry_price,
            size_sol=position.size_sol,
            stop_loss=position.stop_loss,
            take_profit=position.take_profit,
        )

    def close_position(self, token_address: str, close_price: float, reason: str) -> Position | None:
        position = self.open_positions.pop(token_address, None)
        if position is None:
            return None
        position.status = "closed"
        position.close_price = close_price
        position.closed_at = datetime.utcnow()
        position.close_reason = reason
        self.closed_positions.append(position)
        log.info(
            "portfolio.position_closed",
            token=token_address,
            symbol=position.symbol,
            reason=reason,
            pnl_pct=position.pnl_pct,
            pnl_sol=position.pnl_sol,
        )
        return position

    def summary(self) -> dict:
        realized_pnl_sol = sum(p.pnl_sol or 0.0 for p in self.closed_positions)
        wins = sum(1 for p in self.closed_positions if (p.pnl_sol or 0) > 0)
        losses = sum(1 for p in self.closed_positions if (p.pnl_sol or 0) <= 0)
        return {
            "open_positions": self.open_count,
            "closed_positions": len(self.closed_positions),
            "realized_pnl_sol": realized_pnl_sol,
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / len(self.closed_positions)) if self.closed_positions else None,
        }
