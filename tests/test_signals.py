import math
from datetime import datetime, timedelta

from memebot.config import ExitsConfig, StrategyConfig
from memebot.models import Candle
from memebot.strategy.signals import generate_entry_signal


def make_candles(closes, highs=None, lows=None, volumes=None, start=None, step_hours=4):
    start = start or datetime(2026, 1, 1)
    n = len(closes)
    highs = highs or [c * 1.005 for c in closes]
    lows = lows or [c * 0.995 for c in closes]
    volumes = volumes or [1000.0] * n
    return [
        Candle(
            timestamp=start + timedelta(hours=step_hours * i),
            open=closes[i],
            high=highs[i],
            low=lows[i],
            close=closes[i],
            volume=volumes[i],
        )
        for i in range(n)
    ]


def make_triggering_4h_candles():
    """A gentle, oscillating uptrend (keeps RSI in the healthy 50-75 band)
    followed by a volume-confirmed breakout candle that clears the upper
    Bollinger Band — a real, non-stubbed candle series that makes
    generate_entry_signal's default config say should_enter=True."""
    closes = []
    base = 100.0
    for i in range(29):
        base *= 1.004
        osc = 1.0 + 0.018 * math.sin(i * 1.3)
        closes.append(base * osc)
    closes.append(closes[-1] * 1.04)
    highs = [c * 1.005 for c in closes[:-1]] + [closes[-1] * 1.005]
    volumes = [1000.0] * 29 + [2000.0]
    return make_candles(closes, highs=highs, volumes=volumes)


def make_daily_uptrend_candles(n=30):
    closes = [100 * (1.01**i) for i in range(n)]
    return make_candles(closes, step_hours=24)


def make_daily_downtrend_candles(n=30):
    closes = [100 * (0.99**i) for i in range(n)]
    return make_candles(closes, step_hours=24)


def test_baseline_fixture_actually_triggers_without_higher_tf_check():
    cfg = StrategyConfig(require_higher_tf_confirmation=False)
    signal = generate_entry_signal(make_triggering_4h_candles(), cfg, ExitsConfig())
    assert signal.should_enter is True


def test_higher_tf_none_skips_the_check_entirely():
    cfg = StrategyConfig(require_higher_tf_confirmation=True)
    signal = generate_entry_signal(make_triggering_4h_candles(), cfg, ExitsConfig(), higher_tf_candles=None)
    assert signal.should_enter is True


def test_higher_tf_uptrend_confirms_entry():
    cfg = StrategyConfig(require_higher_tf_confirmation=True)
    signal = generate_entry_signal(
        make_triggering_4h_candles(), cfg, ExitsConfig(), higher_tf_candles=make_daily_uptrend_candles()
    )
    assert signal.should_enter is True
    assert any("Higher-timeframe trend confirms" in r for r in signal.reasons)


def test_higher_tf_downtrend_blocks_entry():
    cfg = StrategyConfig(require_higher_tf_confirmation=True)
    signal = generate_entry_signal(
        make_triggering_4h_candles(), cfg, ExitsConfig(), higher_tf_candles=make_daily_downtrend_candles()
    )
    assert signal.should_enter is False
    assert any("fighting the broader trend" in r for r in signal.reasons)


def test_higher_tf_empty_list_blocks_entry_as_not_enough_history():
    cfg = StrategyConfig(require_higher_tf_confirmation=True)
    signal = generate_entry_signal(make_triggering_4h_candles(), cfg, ExitsConfig(), higher_tf_candles=[])
    assert signal.should_enter is False
    assert any("Not enough higher-timeframe history" in r for r in signal.reasons)


def test_higher_tf_too_few_candles_blocks_entry():
    cfg = StrategyConfig(require_higher_tf_confirmation=True)
    short_history = make_daily_uptrend_candles(n=cfg.higher_tf_ema_slow - 1)
    signal = generate_entry_signal(make_triggering_4h_candles(), cfg, ExitsConfig(), higher_tf_candles=short_history)
    assert signal.should_enter is False
    assert any("Not enough higher-timeframe history" in r for r in signal.reasons)


def test_disabled_config_ignores_higher_tf_even_if_downtrend_supplied():
    cfg = StrategyConfig(require_higher_tf_confirmation=False)
    signal = generate_entry_signal(
        make_triggering_4h_candles(), cfg, ExitsConfig(), higher_tf_candles=make_daily_downtrend_candles()
    )
    assert signal.should_enter is True
