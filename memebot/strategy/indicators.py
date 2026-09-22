"""Pure technical indicator functions over a list of closes/candles.
No external TA library dependency — these are simple enough to implement
directly and verify with unit tests.
"""

from __future__ import annotations

from memebot.models import Candle


def ema(values: list[float], period: int) -> list[float | None]:
    """Exponential moving average. First `period - 1` entries are None."""
    if period <= 0 or len(values) < period:
        return [None] * len(values)
    result: list[float | None] = [None] * (period - 1)
    multiplier = 2 / (period + 1)
    sma = sum(values[:period]) / period
    result.append(sma)
    prev = sma
    for v in values[period:]:
        current = (v - prev) * multiplier + prev
        result.append(current)
        prev = current
    return result


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """Wilder's RSI."""
    n = len(values)
    if n < period + 1:
        return [None] * n

    result: list[float | None] = [None] * n
    gains = []
    losses = []
    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    result[period] = _rsi_from_avgs(avg_gain, avg_loss)

    for i in range(period + 1, n):
        change = values[i] - values[i - 1]
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        result[i] = _rsi_from_avgs(avg_gain, avg_loss)

    return result


def _rsi_from_avgs(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def bollinger_bands(
    values: list[float], period: int = 20, std_dev: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Returns (upper, middle, lower) bands."""
    n = len(values)
    upper: list[float | None] = [None] * n
    middle: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n

    for i in range(period - 1, n):
        window = values[i - period + 1 : i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / period
        sd = variance**0.5
        middle[i] = mean
        upper[i] = mean + std_dev * sd
        lower[i] = mean - std_dev * sd

    return upper, middle, lower


def atr(candles: list[Candle], period: int = 14) -> list[float | None]:
    """Average True Range (Wilder's smoothing)."""
    n = len(candles)
    if n < period + 1:
        return [None] * n

    true_ranges: list[float] = []
    for i in range(1, n):
        c = candles[i]
        prev_close = candles[i - 1].close
        tr = max(
            c.high - c.low,
            abs(c.high - prev_close),
            abs(c.low - prev_close),
        )
        true_ranges.append(tr)

    result: list[float | None] = [None] * n
    avg = sum(true_ranges[:period]) / period
    result[period] = avg
    for i in range(period, len(true_ranges)):
        avg = (avg * (period - 1) + true_ranges[i]) / period
        result[i + 1] = avg
    return result


def volume_multiplier(candles: list[Candle], lookback: int = 20) -> list[float | None]:
    """Current candle volume vs trailing average volume (excludes current candle)."""
    n = len(candles)
    result: list[float | None] = [None] * n
    for i in range(lookback, n):
        window = [candles[j].volume for j in range(i - lookback, i)]
        avg = sum(window) / lookback
        result[i] = (candles[i].volume / avg) if avg > 0 else None
    return result
