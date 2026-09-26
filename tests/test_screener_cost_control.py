"""Verifies the paid X/Twitter search is only ever called when the on-chain
result is SAFE — that's the fix for real credits being burned on candidates
that were already going to be rejected on-chain regardless of what X shows.
"""

from unittest.mock import MagicMock

from memebot.config import Settings
from memebot.models import SafetyResult, Verdict
from memebot.safety import screener as screener_module
from memebot.safety.screener import SafetyScreener


def make_screener(monkeypatch, tmp_path, onchain_verdict):
    monkeypatch.setattr(screener_module, "REPO_ROOT", tmp_path)
    screener = SafetyScreener(Settings())
    screener.rugcheck = MagicMock()
    screener.rugcheck.get_report.return_value = None
    screener.goplus = MagicMock()
    screener.goplus.get_token_security.return_value = None
    screener.twitter = MagicMock()
    screener.twitter.search_token_mentions.return_value = []

    monkeypatch.setattr(
        screener_module,
        "evaluate_onchain_safety",
        lambda merged, cfg: SafetyResult(verdict=onchain_verdict, reasons=["stub"], report=merged),
    )
    return screener


def test_skips_paid_social_check_when_onchain_is_danger(monkeypatch, tmp_path):
    screener = make_screener(monkeypatch, tmp_path, Verdict.DANGER)
    record = screener.scan("TOKEN", "SYM")

    screener.twitter.search_token_mentions.assert_not_called()
    assert record.social.verdict == Verdict.WARN
    assert "Skipped social check" in record.social.reasons[0]
    assert not record.passed


def test_skips_paid_social_check_when_onchain_is_warn(monkeypatch, tmp_path):
    screener = make_screener(monkeypatch, tmp_path, Verdict.WARN)
    screener.scan("TOKEN", "SYM")

    screener.twitter.search_token_mentions.assert_not_called()


def test_runs_paid_social_check_only_when_onchain_is_safe(monkeypatch, tmp_path):
    screener = make_screener(monkeypatch, tmp_path, Verdict.SAFE)
    screener.scan("TOKEN", "SYM")

    screener.twitter.search_token_mentions.assert_called_once()
