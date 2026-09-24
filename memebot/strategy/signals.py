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


def generate_entry_signal(
    candles: list[Candle],
    strategy_cfg: StrategyConfig,
    exits_cfg: ExitsConfig,
    higher_tf_candles: list[Candle] | None = None,
) -> Signal:
    """higher_tf_candles (e.g. daily candles): an optional additional trend
    filter — don't buy a 4h breakout that's fighting the higher-timeframe
    trend. Only checked when the caller supplies this data AND
    strategy_cfg.require_higher_tf_confirmation is on; callers that don't
    have this data (the backtester, the self-backtest-on-signal check) are
    unaffected, since they only ever test the core 4h logic.
    """
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

    if strategy_cfg.require_higher_tf_confirmation and higher_tf_candles is not None:
        higher_closes = [c.close for c in higher_tf_candles]
        min_higher_history = strategy_cfg.higher_tf_ema_slow
        if len(higher_closes) < min_higher_history:
            ok = False
            reasons.append(
                f"Not enough higher-timeframe history to confirm the broader trend "
                f"(have {len(higher_closes)}, need {min_higher_history})."
            )
        else:
            h_fast = ema(higher_closes, strategy_cfg.higher_tf_ema_fast)[-1]
            h_slow = ema(higher_closes, strategy_cfg.higher_tf_ema_slow)[-1]
            if h_fast is None or h_slow is None:
                ok = False
                reasons.append("Higher-timeframe EMA not ready yet.")
            elif h_fast > h_slow:
                reasons.append("Higher-timeframe trend confirms (not fighting the broader trend).")
            else:
                ok = False
                reasons.append("Higher-timeframe trend is down — skipping to avoid fighting the broader trend.")

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
