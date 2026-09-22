"""4h entry signal: trend + confirmed volume breakout + healthy-not-overextended
momentum. This is intentionally a *confirmation* strategy, not a prediction
one — it only fires after a move has already started showing real volume
behind it, trading a bit of upside for a much lower false-positive rate.

Long-only: the bot buys spot tokens and later sells them, it never shorts.
"""

from __future__ import annotations

from memebot.config import ExitsConfig, StrategyConfig
from memebot.models import Candle, Signal
from memebot.strategy.indicators import atr, bollinger_bands, ema, rsi, volume_multiplier


def generate_entry_signal(candles: list[Candle], strategy_cfg: StrategyConfig, exits_cfg: ExitsConfig) -> Signal:
    min_history = max(strategy_cfg.ema_slow, strategy_cfg.rsi_period, strategy_cfg.bb_period, strategy_cfg.atr_period) + 5
    if len(candles) < min_history:
        return Signal(should_enter=False, reasons=[f"Not enough candle history (have {len(candles)}, need {min_history})."])

    closes = [c.close for c in candles]
    ema_fast = ema(closes, strategy_cfg.ema_fast)
    ema_slow = ema(closes, strategy_cfg.ema_slow)
    rsi_vals = rsi(closes, strategy_cfg.rsi_period)
    upper, _middle, _lower = bollinger_bands(closes, strategy_cfg.bb_period, strategy_cfg.bb_std_dev)
    atr_vals = atr(candles, strategy_cfg.atr_period)
    vol_mult = volume_multiplier(candles, lookback=20)

    i = len(candles) - 1
    reasons: list[str] = []
    ok = True

    if ema_fast[i] is None or ema_slow[i] is None:
        return Signal(should_enter=False, reasons=["EMA not ready yet."])

    if ema_fast[i] > ema_slow[i]:
        reasons.append(f"Uptrend confirmed: EMA{strategy_cfg.ema_fast} above EMA{strategy_cfg.ema_slow}.")
    else:
        ok = False
        reasons.append(f"No uptrend: EMA{strategy_cfg.ema_fast} below EMA{strategy_cfg.ema_slow}.")

    current_price = closes[i]
    if upper[i] is not None and current_price >= upper[i]:
        reasons.append("Price broke above the upper Bollinger Band.")
    else:
        ok = False
        reasons.append("No confirmed breakout above the upper Bollinger Band.")

    if vol_mult[i] is not None and vol_mult[i] >= strategy_cfg.min_breakout_volume_multiplier:
        reasons.append(f"Breakout volume confirmed ({vol_mult[i]:.2f}x the 20-candle average).")
    else:
        ok = False
        got = f"{vol_mult[i]:.2f}x" if vol_mult[i] is not None else "unknown"
        reasons.append(
            f"Breakout volume not confirmed (got {got}, need >= {strategy_cfg.min_breakout_volume_multiplier}x) "
            "— could be a low-liquidity fake-out."
        )

    if rsi_vals[i] is None:
        ok = False
        reasons.append("RSI not ready yet.")
    elif rsi_vals[i] > strategy_cfg.rsi_overbought:
        ok = False
        reasons.append(f"RSI {rsi_vals[i]:.1f} already overbought (> {strategy_cfg.rsi_overbought}) — too extended to chase.")
    elif rsi_vals[i] < 50:
        ok = False
        reasons.append(f"RSI {rsi_vals[i]:.1f} below 50 — momentum not confirmed.")
    else:
        reasons.append(f"RSI {rsi_vals[i]:.1f} shows healthy, non-extended bullish momentum.")

    if atr_vals[i] is None:
        ok = False
        reasons.append("ATR not available to size a stop-loss.")

    if not ok:
        return Signal(should_enter=False, reasons=reasons)

    stop_distance = atr_vals[i] * exits_cfg.stop_loss_atr_multiplier
    stop_loss = current_price - stop_distance
    take_profit = current_price + stop_distance * exits_cfg.take_profit_risk_reward

    return Signal(
        should_enter=True,
        reasons=reasons,
        entry_price=current_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        atr=atr_vals[i],
    )
