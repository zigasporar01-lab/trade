"""Backtests the 4h entry/exit strategy against historical OHLCV candles by
reusing the exact same signal function the live bot calls
(memebot.strategy.signals.generate_entry_signal) — so results here actually
reflect what the live code would have done, not a reimplementation that
could silently drift from it.

What this DOES validate: whether the technical strategy (trend + confirmed
breakout + RSI + ATR stop / R:R target / trailing stop / time exit) has an
edge on real historical price action.

What this CANNOT validate, and never claims to:
  - The on-chain/social safety gate. RugCheck and GoPlus only expose a
    token's *current* state — there is no historical snapshot of whether
    mint authority was renounced or liquidity was locked at some point
    three months ago. A backtest cannot replay that check.
  - Survivorship bias. Only pools that still exist and are still indexed
    by GeckoTerminal can be backtested at all — tokens that rugged and
    vanished aren't in this data, which flatters any strategy tested this
    way. Treat results as an upper bound on real performance, not a
    prediction of it.
  - Perfect fills. Exit simulation checks each subsequent candle's
    high/low against the stop/target — a reasonable approximation, not a
    tick-by-tick fill simulation. Slippage beyond the configured
    `slippage_bps` isn't modeled at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from memebot.config import ExitsConfig, StrategyConfig, TradingConfig
from memebot.models import Candle
from memebot.risk.position_sizing import size_position
from memebot.strategy.signals import generate_entry_signal


@dataclass
class BacktestTrade:
    symbol: str
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    stop_loss: float
    take_profit: float
    size_sol: float
    pnl_sol: float
    pnl_pct: float
    r_multiple: float  # pnl relative to initial risk distance; size-independent trade quality
    exit_reason: str


@dataclass
class BacktestResult:
    symbol: str
    starting_capital_sol: float
    ending_capital_sol: float
    trades: list[BacktestTrade] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        pnls = [t.pnl_sol for t in self.trades]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        r_multiples = [t.r_multiple for t in self.trades]

        # Max drawdown over the equity curve implied by sequential trade PnLs.
        running = self.starting_capital_sol
        peak = running
        max_dd_pct = 0.0
        for pnl in pnls:
            running += pnl
            peak = max(peak, running)
            if peak > 0:
                max_dd_pct = max(max_dd_pct, (peak - running) / peak)

        return {
            "total_trades": len(self.trades),
            "wins": wins,
            "losses": losses,
            "win_rate": (wins / len(pnls)) if pnls else None,
            "total_pnl_sol": sum(pnls),
            "total_return_pct": (
                (self.ending_capital_sol - self.starting_capital_sol) / self.starting_capital_sol
                if self.starting_capital_sol
                else None
            ),
            "avg_r_multiple": (sum(r_multiples) / len(r_multiples)) if r_multiples else None,
            "best_trade_sol": max(pnls) if pnls else None,
            "worst_trade_sol": min(pnls) if pnls else None,
            "max_drawdown_pct": max_dd_pct,
        }


def _simulate_exit(
    candles: list[Candle],
    entry_index: int,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    risk_unit: float,
    exits_cfg: ExitsConfig,
) -> tuple[float, int, str]:
    """Mirrors memebot.core.bot.MemeBot.monitor_positions()'s exit rules,
    walking forward candle-by-candle instead of polling live prices.

    On a candle that could satisfy both the stop and the target (a large
    range candle), the stop is checked first — the conservative assumption.
    """
    high_water_mark = entry_price
    trailing_active = False
    current_stop = stop_loss
    entry_time = candles[entry_index].timestamp
    max_hold_until = entry_time + timedelta(hours=exits_cfg.max_hold_hours)

    for j in range(entry_index + 1, len(candles)):
        c = candles[j]

        if c.low <= current_stop:
            return current_stop, j, "stop_loss"
        if c.high >= take_profit:
            return take_profit, j, "take_profit"
        if c.timestamp >= max_hold_until:
            return c.close, j, "max_hold_time"

        if c.high > high_water_mark:
            high_water_mark = c.high
        if not trailing_active and risk_unit > 0:
            gained_r = (high_water_mark - entry_price) / risk_unit
            if gained_r >= exits_cfg.trailing_stop_activate_rr:
                trailing_active = True
        if trailing_active:
            new_stop = high_water_mark - risk_unit
            if new_stop > current_stop:
                current_stop = new_stop

    # Ran out of history with the trade still open — close it at the last
    # available price so it's still counted rather than silently dropped.
    last = candles[-1]
    return last.close, len(candles) - 1, "end_of_data"


def run_backtest(
    candles: list[Candle],
    symbol: str,
    strategy_cfg: StrategyConfig,
    exits_cfg: ExitsConfig,
    trading_cfg: TradingConfig,
    starting_capital_sol: float | None = None,
    compounding: bool = True,
) -> BacktestResult:
    """Walks the candle series chronologically. At each point, only candles
    up to and including the current index are ever shown to the signal
    function — no lookahead. One position at a time per symbol.
    """
    capital = starting_capital_sol if starting_capital_sol is not None else trading_cfg.capital_sol
    starting_capital = capital
    trades: list[BacktestTrade] = []

    i = 0
    n = len(candles)
    while i < n:
        window = candles[: i + 1]
        signal = generate_entry_signal(window, strategy_cfg, exits_cfg)
        if not signal.should_enter:
            i += 1
            continue

        risk_unit = signal.entry_price - signal.stop_loss
        if risk_unit <= 0:
            i += 1
            continue

        sizing = size_position(
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            capital_sol=capital,
            open_positions_sol=0.0,
            cfg=trading_cfg,
        )
        if sizing.rejected or capital <= 0:
            i += 1
            continue

        exit_price, exit_index, exit_reason = _simulate_exit(
            candles, i, signal.entry_price, signal.stop_loss, signal.take_profit, risk_unit, exits_cfg
        )

        pnl_pct = (exit_price - signal.entry_price) / signal.entry_price
        pnl_sol = sizing.size_sol * pnl_pct
        r_multiple = (exit_price - signal.entry_price) / risk_unit

        trades.append(
            BacktestTrade(
                symbol=symbol,
                entry_time=candles[i].timestamp,
                entry_price=signal.entry_price,
                exit_time=candles[exit_index].timestamp,
                exit_price=exit_price,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                size_sol=sizing.size_sol,
                pnl_sol=pnl_sol,
                pnl_pct=pnl_pct,
                r_multiple=r_multiple,
                exit_reason=exit_reason,
            )
        )

        if compounding:
            capital += pnl_sol
        i = exit_index + 1

    return BacktestResult(symbol=symbol, starting_capital_sol=starting_capital, ending_capital_sol=capital, trades=trades)
