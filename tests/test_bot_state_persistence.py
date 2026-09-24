"""Verifies MemeBot actually restores open positions and risk state on
construction — not just that StateStore itself works in isolation.
Network clients are constructed but never called (httpx.Client() doesn't
connect until a request is made), so this stays offline.
"""

from datetime import datetime, timedelta

import memebot.core.bot as bot_module
from memebot.config import Settings
from memebot.core.bot import MemeBot
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
    )
    defaults.update(overrides)
    return Position(**defaults)


def test_bot_restores_open_positions_from_previous_session(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_module, "REPO_ROOT", tmp_path)

    pre_store = StateStore(tmp_path / "data" / "state_paper.json")
    pre_store.save([make_position()], RiskState(consecutive_losses=2, manual_pause=True))

    bot = MemeBot(Settings())
    try:
        assert bot.restored_position_count == 1
        assert "TOKEN" in bot.portfolio.open_positions
        assert bot.portfolio.open_positions["TOKEN"].symbol == "FOO"
        assert bot.risk_manager.state.consecutive_losses == 2
        assert bot.risk_manager.state.manual_pause is True
    finally:
        bot.close()


def test_bot_starts_clean_when_no_prior_state_file(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_module, "REPO_ROOT", tmp_path)

    bot = MemeBot(Settings())
    try:
        assert bot.restored_position_count == 0
        assert bot.portfolio.open_positions == {}
    finally:
        bot.close()


def test_opening_a_position_persists_it_for_the_next_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_module, "REPO_ROOT", tmp_path)

    bot = MemeBot(Settings())
    try:
        position = make_position()
        bot.portfolio.open_position(position)
        bot._save_state()
    finally:
        bot.close()

    # Simulate a restart: a brand new MemeBot pointed at the same data dir.
    bot2 = MemeBot(Settings())
    try:
        assert bot2.restored_position_count == 1
        assert "TOKEN" in bot2.portfolio.open_positions
    finally:
        bot2.close()
