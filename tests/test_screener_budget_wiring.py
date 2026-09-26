"""Verifies SafetyScreener actually wires settings.social.daily_x_budget_usd
and a per-mode SpendTracker into its TwitterClient — the wiring, not the
budget-cap logic itself (covered in tests/test_twitter_budget_cap.py).
"""

from memebot.config import Settings
from memebot.safety import screener as screener_module
from memebot.safety.screener import SafetyScreener


def test_screener_builds_tracker_at_mode_scoped_path(monkeypatch, tmp_path):
    monkeypatch.setattr(screener_module, "REPO_ROOT", tmp_path)
    settings = Settings()

    screener = SafetyScreener(settings)

    assert screener.spend_tracker._path == tmp_path / "data" / f"x_spend_{settings.mode_normalized}.json"
    assert screener.twitter._spend_tracker is screener.spend_tracker
    assert screener.twitter._daily_budget_usd == settings.social.daily_x_budget_usd


def test_screener_passes_through_a_custom_budget_value(monkeypatch, tmp_path):
    monkeypatch.setattr(screener_module, "REPO_ROOT", tmp_path)
    settings = Settings()
    settings.social.daily_x_budget_usd = 0.75

    screener = SafetyScreener(settings)

    assert screener.twitter._daily_budget_usd == 0.75
