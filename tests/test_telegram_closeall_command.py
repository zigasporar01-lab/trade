"""Tests TelegramCommandListener._cmd_closeall in isolation — no real
Telegram HTTP calls, just the command's own coordination logic.
"""

from unittest.mock import MagicMock

from memebot.utils.telegram_commands import TelegramCommandListener


def make_listener(open_count=0, close_all_callback=None):
    notifier = MagicMock()
    notifier.send = MagicMock()
    portfolio = MagicMock()
    portfolio.open_count = open_count

    listener = TelegramCommandListener(
        bot_token="dummy",
        chat_id="123",
        notifier=notifier,
        portfolio=portfolio,
        risk_manager=MagicMock(),
        settings=MagicMock(),
        dexscreener=MagicMock(),
        trade_log=MagicMock(),
        close_all_callback=close_all_callback,
    )
    return listener, notifier


def test_closeall_with_no_open_positions_does_nothing():
    callback = MagicMock()
    listener, notifier = make_listener(open_count=0, close_all_callback=callback)

    listener._cmd_closeall()

    callback.assert_not_called()
    notifier.send.assert_called_once()
    assert "No open positions" in notifier.send.call_args[0][0]


def test_closeall_invokes_callback_and_reports_result():
    callback = MagicMock(return_value=2)
    listener, notifier = make_listener(open_count=2, close_all_callback=callback)

    listener._cmd_closeall()

    callback.assert_called_once()
    messages = [call.args[0] for call in notifier.send.call_args_list]
    assert any("Closing all 2" in m for m in messages)
    assert any("2/2 position(s) closed" in m for m in messages)


def test_closeall_without_callback_configured_is_safe():
    listener, notifier = make_listener(open_count=1, close_all_callback=None)

    listener._cmd_closeall()

    notifier.send.assert_called_once()
    assert "isn't wired up" in notifier.send.call_args[0][0]
