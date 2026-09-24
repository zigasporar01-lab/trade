"""Verifies evaluate_candidate() actually fetches higher-timeframe (daily)
candles and passes them into generate_entry_signal — the wiring, not the
signal logic itself (already covered by tests/test_signals.py-equivalent
coverage in the strategy layer). A fetch failure must degrade to "couldn't
confirm" (empty list, blocks entry), never silently skip the check.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import memebot.core.bot as bot_module
from memebot.config import Settings
from memebot.core.bot import MemeBot
from memebot.models import Signal

NOW = datetime(2026, 1, 1, 12, 0)


def make_market():
    market = MagicMock()
    market.token_address = "TOKEN"
    market.symbol = "FOO"
    market.pair_address = "PAIR"
    return market


def make_bot_ready_to_signal(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_module, "REPO_ROOT", tmp_path)
    bot = MemeBot(Settings())
    bot.screener.scan = MagicMock(return_value=MagicMock(passed=True))
    bot.screener.is_tradable = MagicMock(return_value=True)
    return bot


def test_fetches_and_passes_higher_tf_candles_on_success(monkeypatch, tmp_path):
    bot = make_bot_ready_to_signal(monkeypatch, tmp_path)
    try:
        main_candles = ["4h_candle"] * 60
        daily_candles = ["1d_candle"] * 30

        def fake_get_ohlcv(network, pool_address, aggregate_hours, limit):
            if aggregate_hours == bot.settings.strategy.higher_tf_aggregate_hours:
                return daily_candles
            return main_candles

        bot.geckoterminal.get_ohlcv = MagicMock(side_effect=fake_get_ohlcv)

        captured = {}

        def fake_signal(candles, strategy_cfg, exits_cfg, higher_tf_candles=None):
            captured["higher_tf_candles"] = higher_tf_candles
            captured["main_candles"] = candles
            return Signal(should_enter=False, reasons=["stub, not entering"])

        monkeypatch.setattr(bot_module, "generate_entry_signal", fake_signal)

        bot.evaluate_candidate(make_market())

        assert captured["main_candles"] == main_candles
        assert captured["higher_tf_candles"] == daily_candles
    finally:
        bot.close()


def test_higher_tf_fetch_failure_passes_empty_list_not_none(monkeypatch, tmp_path):
    bot = make_bot_ready_to_signal(monkeypatch, tmp_path)
    try:
        def fake_get_ohlcv(network, pool_address, aggregate_hours, limit):
            if aggregate_hours == bot.settings.strategy.higher_tf_aggregate_hours:
                raise RuntimeError("network down")
            return ["4h_candle"] * 60

        bot.geckoterminal.get_ohlcv = MagicMock(side_effect=fake_get_ohlcv)

        captured = {}

        def fake_signal(candles, strategy_cfg, exits_cfg, higher_tf_candles=None):
            captured["higher_tf_candles"] = higher_tf_candles
            return Signal(should_enter=False, reasons=["stub"])

        monkeypatch.setattr(bot_module, "generate_entry_signal", fake_signal)

        bot.evaluate_candidate(make_market())

        # Empty list (blocks entry via the real signal function's "not
        # enough history" path), not None (which would silently skip the
        # check entirely) — a fetch failure must never default to permissive.
        assert captured["higher_tf_candles"] == []
    finally:
        bot.close()


def test_skips_higher_tf_fetch_entirely_when_disabled(monkeypatch, tmp_path):
    bot = make_bot_ready_to_signal(monkeypatch, tmp_path)
    try:
        bot.settings.strategy.require_higher_tf_confirmation = False
        bot.geckoterminal.get_ohlcv = MagicMock(return_value=["4h_candle"] * 60)

        captured = {}

        def fake_signal(candles, strategy_cfg, exits_cfg, higher_tf_candles=None):
            captured["higher_tf_candles"] = higher_tf_candles
            return Signal(should_enter=False, reasons=["stub"])

        monkeypatch.setattr(bot_module, "generate_entry_signal", fake_signal)

        bot.evaluate_candidate(make_market())

        assert captured["higher_tf_candles"] is None
        assert bot.geckoterminal.get_ohlcv.call_count == 1  # only the main 4h fetch, no wasted daily call
    finally:
        bot.close()
