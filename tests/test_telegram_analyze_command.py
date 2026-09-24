"""Tests TelegramCommandListener._cmd_analyze in isolation — no real
Telegram HTTP calls, no real trade log file.
"""

from unittest.mock import MagicMock

from memebot.utils.telegram_commands import TelegramCommandListener


def make_listener(trade_log_rows):
    notifier = MagicMock()
    trade_log = MagicMock()
    trade_log.load_all.return_value = trade_log_rows

    listener = TelegramCommandListener(
        bot_token="dummy",
        chat_id="123",
        notifier=notifier,
        portfolio=MagicMock(),
        risk_manager=MagicMock(),
        settings=MagicMock(),
        dexscreener=MagicMock(),
        trade_log=trade_log,
    )
    return listener, notifier


def test_analyze_with_no_trades():
    listener, notifier = make_listener([])
    listener._cmd_analyze()

    notifier.send.assert_called_once()
    message = notifier.send.call_args[0][0]
    assert "Total trades: 0" in message
    assert "No closed trades yet" in message


def test_analyze_with_trades_includes_breakdown_and_suggestions():
    rows = [
        {"symbol": "FOO", "pnl_sol": "0.02", "close_reason": "take_profit"},
        {"symbol": "FOO", "pnl_sol": "-0.01", "close_reason": "stop_loss"},
    ]
    listener, notifier = make_listener(rows)
    listener._cmd_analyze()

    message = notifier.send.call_args[0][0]
    assert "Total trades: 2" in message
    assert "take_profit" in message
    assert "stop_loss" in message
    assert "Suggestions" in message
