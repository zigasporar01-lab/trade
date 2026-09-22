"""Position sizing via the classic 1% rule: risk a fixed % of capital per
trade, sized off the actual stop-loss distance — never a flat token amount.
"""

from __future__ import annotations

from dataclasses import dataclass

from memebot.config import TradingConfig


@dataclass
class SizingResult:
    size_sol: float
    reasons: list[str]
    rejected: bool = False


def size_position(
    entry_price: float,
    stop_loss: float,
    capital_sol: float,
    open_positions_sol: float,
    cfg: TradingConfig,
) -> SizingResult:
    reasons: list[str] = []

    if entry_price <= 0 or stop_loss <= 0 or stop_loss >= entry_price:
        return SizingResult(size_sol=0.0, reasons=["Invalid entry/stop prices for a long position."], rejected=True)

    stop_distance_pct = (entry_price - stop_loss) / entry_price
    if stop_distance_pct <= 0:
        return SizingResult(size_sol=0.0, reasons=["Stop distance is zero or negative."], rejected=True)

    risk_budget_sol = capital_sol * cfg.risk_per_trade_pct
    raw_size_sol = risk_budget_sol / stop_distance_pct
    reasons.append(
        f"Risking {cfg.risk_per_trade_pct:.1%} of {capital_sol:.4f} SOL "
        f"({risk_budget_sol:.5f} SOL) against a {stop_distance_pct:.1%} stop "
        f"-> raw size {raw_size_sol:.5f} SOL."
    )

    max_size_sol = capital_sol * cfg.max_position_size_pct
    size_sol = min(raw_size_sol, max_size_sol)
    if raw_size_sol > max_size_sol:
        reasons.append(
            f"Capped by max position size ({cfg.max_position_size_pct:.0%} of capital = {max_size_sol:.5f} SOL) "
            "— the stop is wide relative to normal risk, so full risk-sized position would be too large."
        )

    remaining_capital = capital_sol - open_positions_sol
    if size_sol > remaining_capital:
        size_sol = max(remaining_capital, 0.0)
        reasons.append(
            f"Reduced to {size_sol:.5f} SOL — only {remaining_capital:.5f} SOL free "
            f"({open_positions_sol:.5f} SOL already committed to open positions)."
        )

    if size_sol <= 0:
        return SizingResult(size_sol=0.0, reasons=reasons + ["No capital available for a new position."], rejected=True)

    return SizingResult(size_sol=size_sol, reasons=reasons, rejected=False)
