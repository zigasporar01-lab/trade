"""Tests the partial-exit mechanic: selling exits.partial_exit_pct of a
position once the trailing stop activates, and correctly blending that
realized profit into the position's final total PnL when it later fully
closes. Broker and price lookups are mocked so this stays offline.

Trigger prices are chosen with clear margin above the 1.5R threshold
(2.0R, not exactly 1.5R) — an exact-boundary float comparison
(gained_r >= 1.5) is fragile to floating-point rounding, as
0.15 / 0.09999999999999998 lands at 1.4999999999999993, not 1.5.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import memebot.core.bot as bot_module
from memebot.config import Settings
from memebot.core.bot import MemeBot
from memebot.execution.broker import FillResult
from memebot.models import Position


def make_position(entry_price=1.0, stop_loss=0.9, size_sol=0.1, size_tokens=100.0):
    # opened_at must be relative to the real current time — monitor_positions
    # compares against datetime.utcnow(), and a hardcoded past date would
    # spuriously trigger the max_hold_time exit before the trailing-stop
    # logic under test ever runs.
    now = datetime.utcnow()
    return Position(
        token_address="TOKEN",
        symbol="FOO",
        entry_price=entry_price,
        size_sol=size_sol,
        size_tokens=size_tokens,
        stop_loss=stop_loss,
        take_profit=1.5,
        risk_unit=entry_price - stop_loss,
        opened_at=now,
        max_hold_until=now + timedelta(hours=8),
        high_water_mark=entry_price,
    )


def make_bot(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_module, "REPO_ROOT", tmp_path)
    return MemeBot(Settings())


def test_partial_exit_fires_when_trailing_stop_activates(monkeypatch, tmp_path):
    bot = make_bot(monkeypatch, tmp_path)
    try:
        bot.settings.exits.partial_exit_enabled = True
        bot.settings.exits.partial_exit_pct = 0.5
        bot.settings.exits.trailing_stop_activate_rr = 1.5

        position = make_position(entry_price=1.0, stop_loss=0.9)  # risk_unit = 0.1

        bot.portfolio.open_position(position)

        # entry + 2.0R = 1.0 + 0.2 = 1.2 — comfortably past the 1.5R threshold
        bot.dexscreener.get_token_pairs = MagicMock(return_value=[MagicMock(price_usd=1.2)])
        bot.broker = MagicMock()
        bot.broker.sell.return_value = FillResult(success=True, filled_price=1.2, filled_size=50.0, tx_signature="x")

        bot.monitor_positions()

        assert position.partial_exit_done is True
        assert position.trailing_active is True
        assert position.size_tokens == 50.0  # half of the original 100
        assert abs(position.size_sol - 0.05) < 1e-9  # half of the original 0.1
        assert position.realized_partial_pnl_sol > 0  # sold above entry, locked in profit
        assert bot.portfolio.open_count == 1  # still open — only half was sold
        bot.broker.sell.assert_called_once()
        assert bot.broker.sell.call_args[0][1] == 50.0  # sold exactly half the tokens
    finally:
        bot.close()


def test_partial_exit_disabled_leaves_full_size_and_just_trails(monkeypatch, tmp_path):
    bot = make_bot(monkeypatch, tmp_path)
    try:
        bot.settings.exits.partial_exit_enabled = False
        bot.settings.exits.trailing_stop_activate_rr = 1.5

        position = make_position(entry_price=1.0, stop_loss=0.9)
        bot.portfolio.open_position(position)

        bot.dexscreener.get_token_pairs = MagicMock(return_value=[MagicMock(price_usd=1.2)])
        bot.broker = MagicMock()

        bot.monitor_positions()

        assert position.trailing_active is True
        assert position.partial_exit_done is False
        assert position.size_tokens == 100.0  # unchanged
        bot.broker.sell.assert_not_called()  # no partial sell attempted
    finally:
        bot.close()


def test_partial_exit_only_fires_once(monkeypatch, tmp_path):
    bot = make_bot(monkeypatch, tmp_path)
    try:
        bot.settings.exits.partial_exit_enabled = True
        bot.settings.exits.partial_exit_pct = 0.5
        bot.settings.exits.trailing_stop_activate_rr = 1.5

        position = make_position(entry_price=1.0, stop_loss=0.9)
        bot.portfolio.open_position(position)

        bot.dexscreener.get_token_pairs = MagicMock(return_value=[MagicMock(price_usd=1.2)])
        bot.broker = MagicMock()
        bot.broker.sell.return_value = FillResult(success=True, filled_price=1.2, filled_size=50.0, tx_signature="x")

        bot.monitor_positions()
        assert bot.broker.sell.call_count == 1

        # Price keeps rising on subsequent cycles — must not sell again.
        bot.dexscreener.get_token_pairs = MagicMock(return_value=[MagicMock(price_usd=1.3)])
        bot.monitor_positions()
        assert bot.broker.sell.call_count == 1  # unchanged
    finally:
        bot.close()


def test_failed_partial_sell_is_retried_next_cycle(monkeypatch, tmp_path):
    bot = make_bot(monkeypatch, tmp_path)
    try:
        bot.settings.exits.partial_exit_enabled = True
        bot.settings.exits.partial_exit_pct = 0.5
        bot.settings.exits.trailing_stop_activate_rr = 1.5

        position = make_position(entry_price=1.0, stop_loss=0.9)
        bot.portfolio.open_position(position)

        bot.dexscreener.get_token_pairs = MagicMock(return_value=[MagicMock(price_usd=1.2)])
        bot.broker = MagicMock()
        bot.broker.sell.side_effect = [
            FillResult(success=False, filled_price=None, filled_size=None, tx_signature=None, error="rejected"),
            FillResult(success=True, filled_price=1.21, filled_size=50.0, tx_signature="x"),
        ]

        bot.monitor_positions()
        assert position.partial_exit_done is False
        assert position.size_tokens == 100.0  # unchanged after the failed attempt

        bot.monitor_positions()
        assert position.partial_exit_done is True
        assert position.size_tokens == 50.0
    finally:
        bot.close()


def test_final_close_blends_partial_and_remaining_pnl(monkeypatch, tmp_path):
    bot = make_bot(monkeypatch, tmp_path)
    try:
        bot.settings.exits.partial_exit_enabled = True
        bot.settings.exits.partial_exit_pct = 0.5
        bot.settings.exits.trailing_stop_activate_rr = 1.5

        position = make_position(entry_price=1.0, stop_loss=0.9, size_sol=0.1, size_tokens=100.0)
        bot.portfolio.open_position(position)

        bot.broker = MagicMock()

        # Cycle 1: price hits 1.2 (2.0R) -> trailing activates, half sold at 1.2.
        # Trailing stop then updates in the same cycle to high_water_mark(1.2) - risk_unit(0.1) = 1.1.
        bot.dexscreener.get_token_pairs = MagicMock(return_value=[MagicMock(price_usd=1.2)])
        bot.broker.sell.return_value = FillResult(success=True, filled_price=1.2, filled_size=50.0, tx_signature="x")
        bot.monitor_positions()

        expected_partial_pnl = 0.05 * (1.2 - 1.0) / 1.0  # half the original 0.1 SOL, at 20% gain
        assert abs(position.realized_partial_pnl_sol - expected_partial_pnl) < 1e-9
        assert abs(position.stop_loss - 1.1) < 1e-9

        # Cycle 2: price drops to 1.05, clearly below the trailed 1.1 stop.
        bot.dexscreener.get_token_pairs = MagicMock(return_value=[MagicMock(price_usd=1.05)])
        bot.broker.sell.return_value = FillResult(success=True, filled_price=1.05, filled_size=50.0, tx_signature="x")
        bot.monitor_positions()

        assert bot.portfolio.open_count == 0
        rows = bot.trade_log.load_all()
        assert len(rows) == 1
        final_pnl_sol = float(rows[0]["pnl_sol"])

        remaining_pnl = 0.05 * (1.05 - 1.0) / 1.0  # remaining half, closed at 1.05
        expected_total = expected_partial_pnl + remaining_pnl
        assert abs(final_pnl_sol - expected_total) < 1e-9
        assert final_pnl_sol > 0  # both legs were sold above entry, net profitable overall
    finally:
        bot.close()
