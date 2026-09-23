from datetime import datetime

from memebot.core.trade_log import TradeLog
from memebot.models import Position


def make_closed_position(symbol="FOO", pnl_pct=0.1, size_sol=0.1):
    entry_price = 1.0
    close_price = entry_price * (1 + pnl_pct)
    return Position(
        token_address="TOKEN",
        symbol=symbol,
        entry_price=entry_price,
        size_sol=size_sol,
        size_tokens=100.0,
        stop_loss=entry_price * 0.9,
        take_profit=entry_price * 1.2,
        risk_unit=entry_price * 0.1,
        opened_at=datetime(2026, 1, 1, 10, 0),
        max_hold_until=datetime(2026, 1, 1, 18, 0),
        high_water_mark=entry_price,
        status="closed",
        close_price=close_price,
        closed_at=datetime(2026, 1, 1, 14, 0),
        close_reason="take_profit",
    )


def test_creates_file_with_header_on_first_use(tmp_path):
    log = TradeLog(tmp_path / "trades.csv")
    assert log.path.exists()
    assert log.load_all() == []


def test_records_and_reloads_a_trade(tmp_path):
    log = TradeLog(tmp_path / "trades.csv")
    log.record(make_closed_position(symbol="FOO", pnl_pct=0.1, size_sol=0.1), mode="paper")

    rows = log.load_all()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "FOO"
    assert rows[0]["mode"] == "paper"
    assert rows[0]["close_reason"] == "take_profit"


def test_survives_reopening_the_same_file(tmp_path):
    path = tmp_path / "trades.csv"
    log1 = TradeLog(path)
    log1.record(make_closed_position(symbol="FOO"), mode="paper")

    # Simulate a restart: a brand new TradeLog instance pointed at the same file.
    log2 = TradeLog(path)
    rows = log2.load_all()
    assert len(rows) == 1
    assert rows[0]["symbol"] == "FOO"


def test_summary_aggregates_wins_and_losses(tmp_path):
    log = TradeLog(tmp_path / "trades.csv")
    log.record(make_closed_position(symbol="WIN1", pnl_pct=0.2, size_sol=0.1), mode="paper")
    log.record(make_closed_position(symbol="WIN2", pnl_pct=0.1, size_sol=0.1), mode="paper")
    log.record(make_closed_position(symbol="LOSS1", pnl_pct=-0.05, size_sol=0.1), mode="paper")

    s = log.summary()
    assert s["total_trades"] == 3
    assert s["wins"] == 2
    assert s["losses"] == 1
    assert abs(s["win_rate"] - 2 / 3) < 1e-9
    assert s["total_pnl_sol"] > 0


def test_summary_on_empty_log(tmp_path):
    log = TradeLog(tmp_path / "trades.csv")
    s = log.summary()
    assert s["total_trades"] == 0
    assert s["win_rate"] is None
    assert s["total_pnl_sol"] == 0
