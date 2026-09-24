from datetime import datetime, timedelta
from pathlib import Path

from memebot.core.state_store import StateStore
from memebot.models import Position
from memebot.risk.risk_manager import RiskState

NOW = datetime(2026, 1, 1, 12, 0)


def make_position(**overrides):
    defaults = dict(
        token_address="TOKEN",
        symbol="FOO",
        entry_price=1.0,
        size_sol=0.1,
        size_tokens=100.0,
        stop_loss=0.9,
        take_profit=1.2,
        risk_unit=0.1,
        opened_at=NOW,
        max_hold_until=NOW + timedelta(hours=8),
        high_water_mark=1.05,
        trailing_active=True,
        partial_exit_done=True,
        realized_partial_pnl_sol=0.003,
    )
    defaults.update(overrides)
    return Position(**defaults)


def test_load_on_missing_file_returns_empty(tmp_path):
    store = StateStore(tmp_path / "does-not-exist.json")
    positions, risk_state = store.load()
    assert positions == []
    assert risk_state is None


def test_round_trips_a_position(tmp_path):
    store = StateStore(tmp_path / "state.json")
    original = make_position()
    store.save([original], RiskState())

    positions, _risk_state = store.load()
    assert len(positions) == 1
    restored = positions[0]
    assert restored.token_address == original.token_address
    assert restored.symbol == original.symbol
    assert restored.entry_price == original.entry_price
    assert restored.opened_at == original.opened_at
    assert restored.max_hold_until == original.max_hold_until
    assert restored.trailing_active is True
    assert restored.partial_exit_done is True
    assert restored.realized_partial_pnl_sol == 0.003


def test_round_trips_risk_state_with_pause(tmp_path):
    store = StateStore(tmp_path / "state.json")
    paused_until = NOW + timedelta(hours=4)
    risk_state = RiskState(
        day="2026-01-01", daily_pnl_sol=-0.02, consecutive_losses=3, paused_until=paused_until, manual_pause=True
    )
    store.save([], risk_state)

    _positions, restored = store.load()
    assert restored.day == "2026-01-01"
    assert restored.daily_pnl_sol == -0.02
    assert restored.consecutive_losses == 3
    assert restored.paused_until == paused_until
    assert restored.manual_pause is True


def test_round_trips_risk_state_with_no_pause(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save([], RiskState())
    _positions, restored = store.load()
    assert restored.paused_until is None
    assert restored.manual_pause is False


def test_no_leftover_temp_files_after_save(tmp_path):
    store = StateStore(tmp_path / "state.json")
    store.save([make_position()], RiskState())
    files = list(tmp_path.iterdir())
    assert files == [tmp_path / "state.json"]


def test_multiple_positions_round_trip_in_order(tmp_path):
    store = StateStore(tmp_path / "state.json")
    p1 = make_position(token_address="A", symbol="AAA")
    p2 = make_position(token_address="B", symbol="BBB")
    store.save([p1, p2], RiskState())

    positions, _ = store.load()
    assert [p.symbol for p in positions] == ["AAA", "BBB"]
