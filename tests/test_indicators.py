from datetime import datetime, timedelta

from memebot.models import Candle
from memebot.strategy.indicators import atr, bollinger_bands, ema, rsi, volume_multiplier


def make_candles(closes, highs=None, lows=None, volumes=None):
    now = datetime(2026, 1, 1)
    highs = highs or [c * 1.01 for c in closes]
    lows = lows or [c * 0.99 for c in closes]
    volumes = volumes or [1000] * len(closes)
    return [
        Candle(timestamp=now + timedelta(hours=4 * i), open=closes[i], high=highs[i], low=lows[i], close=closes[i], volume=volumes[i])
        for i in range(len(closes))
    ]


def test_ema_matches_sma_seed_then_smooths():
    values = [10, 11, 12, 13, 14, 15]
    result = ema(values, period=3)
    assert result[0] is None and result[1] is None
    assert result[2] == sum(values[:3]) / 3
    assert result[-1] > result[2]


def test_ema_insufficient_data_returns_all_none():
    assert ema([1, 2], period=5) == [None, None]


def test_rsi_all_gains_is_100():
    values = list(range(1, 20))  # strictly increasing
    result = rsi(values, period=14)
    assert result[14] == 100.0


def test_rsi_all_losses_is_0():
    values = list(range(20, 1, -1))  # strictly decreasing
    result = rsi(values, period=14)
    assert result[14] == 0.0


def test_bollinger_bands_upper_above_middle_above_lower():
    values = [10, 11, 9, 12, 8, 13, 7, 14, 6, 15, 20, 25, 30, 18, 22, 19, 21, 23, 17, 24]
    upper, middle, lower = bollinger_bands(values, period=20, std_dev=2.0)
    assert upper[19] is not None
    assert upper[19] > middle[19] > lower[19]


def test_atr_positive_for_volatile_candles():
    closes = [10, 11, 9, 12, 8, 13, 7, 14, 6, 15, 10, 11, 9, 12, 8]
    candles = make_candles(closes)
    result = atr(candles, period=14)
    assert result[14] is not None
    assert result[14] > 0


def test_volume_multiplier_detects_spike():
    closes = [10] * 25
    volumes = [100] * 20 + [500] + [100] * 4
    candles = make_candles(closes, volumes=volumes)
    result = volume_multiplier(candles, lookback=20)
    assert result[20] == 5.0
