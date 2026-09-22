from memebot.config import TradingConfig
from memebot.risk.risk_manager import RiskManager


def make_manager(**overrides):
    defaults = dict(
        capital_sol=1.0,
        max_concurrent_positions=2,
        max_daily_loss_pct=0.05,
        max_consecutive_losses=3,
        cooldown_minutes_after_loss_streak=240,
    )
    defaults.update(overrides)
    cfg = TradingConfig(**defaults)
    return RiskManager(cfg, capital_sol=1.0)


def test_allows_trade_within_limits():
    rm = make_manager()
    ok, _ = rm.can_open_new_position(open_position_count=0)
    assert ok


def test_blocks_when_max_concurrent_positions_reached():
    rm = make_manager()
    ok, reason = rm.can_open_new_position(open_position_count=2)
    assert not ok
    assert "concurrent" in reason.lower()


def test_daily_loss_limit_halts_trading():
    rm = make_manager()
    rm.record_trade_closed(-0.03)
    rm.record_trade_closed(-0.03)  # total -0.06 SOL > 5% of 1 SOL cap
    ok, reason = rm.can_open_new_position(open_position_count=0)
    assert not ok
    assert "daily loss" in reason.lower()


def test_consecutive_losses_trigger_cooldown():
    rm = make_manager(max_consecutive_losses=3)
    rm.record_trade_closed(-0.001)
    rm.record_trade_closed(-0.001)
    rm.record_trade_closed(-0.001)
    assert rm.state.paused_until is not None
    ok, reason = rm.can_open_new_position(open_position_count=0)
    assert not ok
    assert "cooldown" in reason.lower()


def test_win_resets_consecutive_loss_counter():
    rm = make_manager(max_consecutive_losses=3)
    rm.record_trade_closed(-0.001)
    rm.record_trade_closed(-0.001)
    rm.record_trade_closed(0.01)
    assert rm.state.consecutive_losses == 0
    assert rm.state.paused_until is None
