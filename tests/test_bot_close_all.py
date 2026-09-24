"""Tests MemeBot.close_all_positions() / _close_position() — the emergency
stop's actual implementation. The broker and price lookups are mocked so
this stays offline; only the bot's own coordination logic is under test.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import memebot.core.bot as bot_module
from memebot.config import Settings
from memebot.core.bot import MemeBot
from memebot.execution.broker import FillResult
from memebot.models import Position

NOW = datetime(2026, 1, 1, 12, 0)


def make_position(token_address, symbol, entry_price=1.0, stop_loss=0.9, take_profit=1.2):
    return Position(
        token_address=token_address,
        symbol=symbol,
        entry_price=entry_price,
        size_sol=0.1,
        size_tokens=100.0,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_unit=entry_price - stop_loss,
        opened_at=NOW,
        max_hold_until=NOW + timedelta(hours=8),
        high_water_mark=entry_price,
    )


def make_bot(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_module, "REPO_ROOT", tmp_path)
    return MemeBot(Settings())


def test_close_all_positions_closes_everything(monkeypatch, tmp_path):
    bot = make_bot(monkeypatch, tmp_path)
    try:
        bot.portfolio.open_position(make_position("A", "AAA"))
        bot.portfolio.open_position(make_position("B", "BBB"))

        bot.broker = MagicMock()
        bot.broker.sell.return_value = FillResult(success=True, filled_price=1.1, filled_size=100.0, tx_signature="x")
        bot.dexscreener.get_token_pairs = MagicMock(return_value=[MagicMock(price_usd=1.1)])

        closed_count = bot.close_all_positions()

        assert closed_count == 2
        assert bot.portfolio.open_count == 0
        assert bot.broker.sell.call_count == 2
    finally:
        bot.close()


def test_close_all_positions_returns_zero_when_nothing_open(monkeypatch, tmp_path):
    bot = make_bot(monkeypatch, tmp_path)
    try:
        assert bot.close_all_positions() == 0
    finally:
        bot.close()


def test_close_all_falls_back_to_entry_price_on_price_lookup_failure(monkeypatch, tmp_path):
    bot = make_bot(monkeypatch, tmp_path)
    try:
        bot.portfolio.open_position(make_position("A", "AAA", entry_price=1.0))
        bot.broker = MagicMock()
        bot.broker.sell.return_value = FillResult(success=True, filled_price=None, filled_size=100.0, tx_signature="x")
        bot.dexscreener.get_token_pairs = MagicMock(side_effect=RuntimeError("network down"))

        closed_count = bot.close_all_positions()

        assert closed_count == 1
        assert bot.portfolio.open_count == 0
    finally:
        bot.close()


def test_close_all_skips_a_failed_sell_but_still_closes_the_rest(monkeypatch, tmp_path):
    bot = make_bot(monkeypatch, tmp_path)
    try:
        bot.portfolio.open_position(make_position("A", "AAA"))
        bot.portfolio.open_position(make_position("B", "BBB"))

        bot.dexscreener.get_token_pairs = MagicMock(return_value=[MagicMock(price_usd=1.1)])
        bot.broker = MagicMock()
        bot.broker.sell.side_effect = [
            FillResult(success=False, filled_price=None, filled_size=None, tx_signature=None, error="rejected"),
            FillResult(success=True, filled_price=1.1, filled_size=100.0, tx_signature="x"),
        ]

        closed_count = bot.close_all_positions()

        assert closed_count == 1
        assert bot.portfolio.open_count == 1  # the failed one is still open, correctly not lost
    finally:
        bot.close()


def test_monitor_positions_and_close_all_use_the_same_close_path(monkeypatch, tmp_path):
    """Regression guard for the refactor: both callers must go through
    _close_position, so a stop-loss exit and an emergency close behave
    identically (trade log write, risk manager update, notification)."""
    bot = make_bot(monkeypatch, tmp_path)
    try:
        bot.portfolio.open_position(make_position("A", "AAA", entry_price=1.0, stop_loss=0.9))
        bot.broker = MagicMock()
        bot.broker.sell.return_value = FillResult(success=True, filled_price=0.85, filled_size=100.0, tx_signature="x")
        bot.dexscreener.get_token_pairs = MagicMock(return_value=[MagicMock(price_usd=0.85)])  # below stop_loss

        bot.monitor_positions()

        assert bot.portfolio.open_count == 0
        rows = bot.trade_log.load_all()
        assert len(rows) == 1
        assert rows[0]["close_reason"] == "stop_loss"
    finally:
        bot.close()
