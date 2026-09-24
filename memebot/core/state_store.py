"""Persists open positions and risk-manager state to a local JSON file so
they survive a restart (laptop sleep, a crash, a manual stop). The
persistent trade log already covers *closed* trades — this covers the
state that used to be lost: positions still open, and the risk manager's
daily-loss/loss-streak/manual-pause tracking.

Written atomically (temp file + rename) so a crash mid-write can't leave a
corrupt, half-written state file behind.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from memebot.models import Position
from memebot.risk.risk_manager import RiskState


def _dt_to_str(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _str_to_dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _position_to_dict(p: Position) -> dict:
    return {
        "token_address": p.token_address,
        "symbol": p.symbol,
        "entry_price": p.entry_price,
        "size_sol": p.size_sol,
        "size_tokens": p.size_tokens,
        "stop_loss": p.stop_loss,
        "take_profit": p.take_profit,
        "risk_unit": p.risk_unit,
        "opened_at": _dt_to_str(p.opened_at),
        "max_hold_until": _dt_to_str(p.max_hold_until),
        "high_water_mark": p.high_water_mark,
        "trailing_active": p.trailing_active,
        "partial_exit_done": p.partial_exit_done,
        "realized_partial_pnl_sol": p.realized_partial_pnl_sol,
    }


def _position_from_dict(d: dict) -> Position:
    return Position(
        token_address=d["token_address"],
        symbol=d["symbol"],
        entry_price=d["entry_price"],
        size_sol=d["size_sol"],
        size_tokens=d["size_tokens"],
        stop_loss=d["stop_loss"],
        take_profit=d["take_profit"],
        risk_unit=d["risk_unit"],
        opened_at=_str_to_dt(d["opened_at"]),
        max_hold_until=_str_to_dt(d["max_hold_until"]),
        high_water_mark=d["high_water_mark"],
        trailing_active=d.get("trailing_active", False),
        partial_exit_done=d.get("partial_exit_done", False),
        realized_partial_pnl_sol=d.get("realized_partial_pnl_sol", 0.0),
    )


def _risk_state_to_dict(state: RiskState) -> dict:
    return {
        "day": state.day,
        "daily_pnl_sol": state.daily_pnl_sol,
        "consecutive_losses": state.consecutive_losses,
        "paused_until": _dt_to_str(state.paused_until),
        "manual_pause": state.manual_pause,
    }


def _risk_state_from_dict(d: dict) -> RiskState:
    return RiskState(
        day=d["day"],
        daily_pnl_sol=d["daily_pnl_sol"],
        consecutive_losses=d["consecutive_losses"],
        paused_until=_str_to_dt(d.get("paused_until")),
        manual_pause=d.get("manual_pause", False),
    )


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, positions: list[Position], risk_state: RiskState) -> None:
        data = {
            "positions": [_position_to_dict(p) for p in positions],
            "risk_state": _risk_state_to_dict(risk_state),
        }
        fd, tmp_path = tempfile.mkstemp(dir=str(self.path.parent), prefix=".state_tmp_")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def load(self) -> tuple[list[Position], RiskState | None]:
        if not self.path.exists():
            return [], None
        with open(self.path) as f:
            data = json.load(f)
        positions = [_position_from_dict(d) for d in data.get("positions", [])]
        risk_state = _risk_state_from_dict(data["risk_state"]) if data.get("risk_state") else None
        return positions, risk_state
