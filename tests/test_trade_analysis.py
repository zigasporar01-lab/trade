from memebot.core.trade_analysis import analyze


def make_row(symbol="FOO", pnl_sol=0.01, close_reason="take_profit"):
    return {"symbol": symbol, "pnl_sol": str(pnl_sol), "close_reason": close_reason}


def test_empty_log_reports_no_trades():
    result = analyze([])
    assert result["overall"]["total_trades"] == 0
    assert result["overall"]["win_rate"] is None
    assert "No closed trades yet" in result["suggestions"][0]


def test_overall_stats_computed_correctly():
    rows = [
        make_row(pnl_sol=0.02, close_reason="take_profit"),
        make_row(pnl_sol=-0.01, close_reason="stop_loss"),
        make_row(pnl_sol=0.01, close_reason="take_profit"),
    ]
    result = analyze(rows)
    o = result["overall"]
    assert o["total_trades"] == 3
    assert o["wins"] == 2
    assert o["losses"] == 1
    assert abs(o["win_rate"] - 2 / 3) < 1e-9
    assert abs(o["total_pnl_sol"] - 0.02) < 1e-9


def test_by_reason_breakdown():
    rows = [
        make_row(pnl_sol=0.02, close_reason="take_profit"),
        make_row(pnl_sol=0.03, close_reason="take_profit"),
        make_row(pnl_sol=-0.01, close_reason="stop_loss"),
    ]
    result = analyze(rows)
    assert result["by_reason"]["take_profit"]["count"] == 2
    assert abs(result["by_reason"]["take_profit"]["total_pnl_sol"] - 0.05) < 1e-9
    assert abs(result["by_reason"]["take_profit"]["avg_pnl_sol"] - 0.025) < 1e-9
    assert result["by_reason"]["stop_loss"]["count"] == 1


def test_flags_negative_max_hold_time_pattern():
    rows = [make_row(pnl_sol=-0.005, close_reason="max_hold_time") for _ in range(4)]
    result = analyze(rows)
    joined = " ".join(result["suggestions"])
    assert "max_hold_time" in joined
    assert "max_hold_hours" in joined


def test_does_not_flag_max_hold_time_when_profitable():
    rows = [make_row(pnl_sol=0.005, close_reason="max_hold_time") for _ in range(4)]
    result = analyze(rows)
    joined = " ".join(result["suggestions"])
    assert "lowering exits.max_hold_hours" not in joined


def test_flags_high_stop_loss_share():
    rows = [make_row(pnl_sol=-0.01, close_reason="stop_loss") for _ in range(4)] + [
        make_row(pnl_sol=0.02, close_reason="take_profit")
    ]
    result = analyze(rows)
    joined = " ".join(result["suggestions"])
    assert "entry signal may be too loose" in joined


def test_does_not_flag_stop_loss_share_below_threshold():
    rows = [make_row(pnl_sol=0.01, close_reason="take_profit") for _ in range(4)] + [
        make_row(pnl_sol=-0.01, close_reason="stop_loss")
    ]
    result = analyze(rows)
    joined = " ".join(result["suggestions"])
    assert "entry signal may be too loose" not in joined


def test_flags_repeat_losing_symbol():
    rows = [
        make_row(symbol="RUGGY", pnl_sol=-0.01, close_reason="stop_loss"),
        make_row(symbol="RUGGY", pnl_sol=-0.02, close_reason="stop_loss"),
        make_row(symbol="GOODCOIN", pnl_sol=0.03, close_reason="take_profit"),
    ]
    result = analyze(rows)
    joined = " ".join(result["suggestions"])
    assert "RUGGY" in joined
    assert "GOODCOIN" not in joined


def test_small_sample_gets_a_caution_note():
    rows = [make_row(pnl_sol=0.01)]
    result = analyze(rows)
    joined = " ".join(result["suggestions"])
    assert "too small a sample" in joined


def test_handles_missing_or_malformed_pnl_gracefully():
    rows = [{"symbol": "FOO", "pnl_sol": "", "close_reason": "take_profit"}, {"symbol": "BAR"}]
    result = analyze(rows)
    assert result["overall"]["total_trades"] == 2
    assert result["overall"]["win_rate"] is None  # no valid numeric pnl values at all
