"""Circuit breakers: daily loss limit, consecutive-loss cooldown, max
concurrent positions. This is what stops the bot from "revenge trading"
after a bad run — a real risk with fast 4h memecoin cycles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import structlog

from memebot.config import TradingConfig

log = structlog.get_logger(__name__)


@dataclass
class RiskState:
    day: str = field(default_factory=lambda: datetime.utcnow().strftime("%Y-%m-%d"))
    daily_pnl_sol: float = 0.0
    consecutive_losses: int = 0
    paused_until: datetime | None = None


class RiskManager:
    def __init__(self, cfg: TradingConfig, capital_sol: float) -> None:
        self.cfg = cfg
        self.capital_sol = capital_sol
        self.state = RiskState()

    def _roll_day_if_needed(self) -> None:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        if today != self.state.day:
            log.info("risk.day_rolled", previous_day=self.state.day, previous_pnl_sol=self.state.daily_pnl_sol)
            self.state = RiskState(day=today)

    def can_open_new_position(self, open_position_count: int) -> tuple[bool, str]:
        self._roll_day_if_needed()

        if self.state.paused_until and datetime.utcnow() < self.state.paused_until:
            return False, f"Trading paused until {self.state.paused_until.isoformat()} (loss-streak cooldown)."

        if open_position_count >= self.cfg.max_concurrent_positions:
            return False, f"Max concurrent positions reached ({self.cfg.max_concurrent_positions})."

        daily_loss_limit_sol = -abs(self.capital_sol * self.cfg.max_daily_loss_pct)
        if self.state.daily_pnl_sol <= daily_loss_limit_sol:
            return False, (
                f"Daily loss limit hit ({self.state.daily_pnl_sol:.5f} SOL <= "
                f"{daily_loss_limit_sol:.5f} SOL) — no new trades until tomorrow (UTC)."
            )

        return True, "OK"

    def record_trade_closed(self, pnl_sol: float) -> None:
        self._roll_day_if_needed()
        self.state.daily_pnl_sol += pnl_sol

        if pnl_sol < 0:
            self.state.consecutive_losses += 1
        else:
            self.state.consecutive_losses = 0

        if self.state.consecutive_losses >= self.cfg.max_consecutive_losses:
            self.state.paused_until = datetime.utcnow() + timedelta(
                minutes=self.cfg.cooldown_minutes_after_loss_streak
            )
            log.warning(
                "risk.loss_streak_cooldown_triggered",
                consecutive_losses=self.state.consecutive_losses,
                paused_until=self.state.paused_until.isoformat(),
            )

        log.info(
            "risk.trade_closed",
            pnl_sol=pnl_sol,
            daily_pnl_sol=self.state.daily_pnl_sol,
            consecutive_losses=self.state.consecutive_losses,
        )
