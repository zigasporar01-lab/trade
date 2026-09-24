from memebot.core.bot import _format_self_backtest


def test_none_summary_means_not_enough_history():
    assert "not enough history" in _format_self_backtest(None)


def test_zero_trades_is_reported_as_first_occurrence_not_an_error():
    summary = {"total_trades": 0, "win_rate": None, "total_pnl_sol": 0.0}
    result = _format_self_backtest(summary)
    assert "0 prior occurrences" in result
    assert "first time firing" in result


def test_formats_trade_count_win_rate_and_pnl():
    summary = {"total_trades": 3, "win_rate": 0.667, "total_pnl_sol": 0.0123}
    result = _format_self_backtest(summary)
    assert "3 prior trade(s)" in result
    assert "67% win rate" in result
    assert "+0.01230 SOL" in result
