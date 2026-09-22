from memebot.config import TradingConfig
from memebot.risk.position_sizing import size_position


def base_cfg(**overrides):
    defaults = dict(capital_sol=1.0, risk_per_trade_pct=0.01, max_position_size_pct=0.15)
    defaults.update(overrides)
    return TradingConfig(**defaults)


def test_sizes_by_stop_distance_risk_rule():
    # max_position_size_pct set high so the cap doesn't interfere with this check.
    cfg = base_cfg(max_position_size_pct=0.9)
    # entry 100, stop 95 -> 5% stop distance. risk budget = 1% of 1 SOL = 0.01 SOL.
    # size = 0.01 / 0.05 = 0.2 SOL
    result = size_position(entry_price=100, stop_loss=95, capital_sol=1.0, open_positions_sol=0.0, cfg=cfg)
    assert not result.rejected
    assert abs(result.size_sol - 0.2) < 1e-9


def test_caps_at_max_position_size_pct_for_tight_stop():
    cfg = base_cfg()
    # entry 100, stop 99.9 -> 0.1% stop distance -> raw size would be huge, must cap at 15%.
    result = size_position(entry_price=100, stop_loss=99.9, capital_sol=1.0, open_positions_sol=0.0, cfg=cfg)
    assert not result.rejected
    assert abs(result.size_sol - 0.15) < 1e-9


def test_rejects_invalid_stop_above_entry():
    cfg = base_cfg()
    result = size_position(entry_price=100, stop_loss=101, capital_sol=1.0, open_positions_sol=0.0, cfg=cfg)
    assert result.rejected
    assert result.size_sol == 0.0


def test_reduces_size_when_capital_already_committed():
    cfg = base_cfg()
    # normally would size 0.2 SOL, but only 0.05 SOL free.
    result = size_position(entry_price=100, stop_loss=95, capital_sol=1.0, open_positions_sol=0.95, cfg=cfg)
    assert not result.rejected
    assert abs(result.size_sol - 0.05) < 1e-9


def test_rejects_when_no_capital_free():
    cfg = base_cfg()
    result = size_position(entry_price=100, stop_loss=95, capital_sol=1.0, open_positions_sol=1.0, cfg=cfg)
    assert result.rejected
    assert result.size_sol == 0.0
