"""Tests the two-scan reconfirmation rule in isolation (no network calls) by
driving CandidateHistory/ScanRecord directly rather than the full SafetyScreener
(which makes live HTTP requests).
"""

from datetime import datetime, timedelta

from memebot.models import SafetyResult, SocialResult, Verdict
from memebot.safety.screener import CandidateHistory, ScanRecord

SAFE_ONCHAIN = SafetyResult(verdict=Verdict.SAFE, reasons=[], report=None)
SAFE_SOCIAL = SocialResult(verdict=Verdict.SAFE, reasons=[], report=None)
DANGER_ONCHAIN = SafetyResult(verdict=Verdict.DANGER, reasons=["bad"], report=None)


def test_single_passing_scan_is_not_enough():
    history = CandidateHistory("TOKEN")
    history.scans.append(ScanRecord(timestamp=datetime(2026, 1, 1, 12, 0), onchain=SAFE_ONCHAIN, social=SAFE_SOCIAL))
    assert not history.is_confirmed(required_scans=2, gap_minutes=15)


def test_two_passing_scans_too_close_together_not_confirmed():
    history = CandidateHistory("TOKEN")
    history.scans.append(ScanRecord(timestamp=datetime(2026, 1, 1, 12, 0), onchain=SAFE_ONCHAIN, social=SAFE_SOCIAL))
    history.scans.append(ScanRecord(timestamp=datetime(2026, 1, 1, 12, 5), onchain=SAFE_ONCHAIN, social=SAFE_SOCIAL))
    assert not history.is_confirmed(required_scans=2, gap_minutes=15)


def test_two_passing_scans_far_enough_apart_confirmed():
    history = CandidateHistory("TOKEN")
    history.scans.append(ScanRecord(timestamp=datetime(2026, 1, 1, 12, 0), onchain=SAFE_ONCHAIN, social=SAFE_SOCIAL))
    history.scans.append(ScanRecord(timestamp=datetime(2026, 1, 1, 12, 20), onchain=SAFE_ONCHAIN, social=SAFE_SOCIAL))
    assert history.is_confirmed(required_scans=2, gap_minutes=15)


def test_a_single_danger_scan_breaks_confirmation():
    history = CandidateHistory("TOKEN")
    history.scans.append(ScanRecord(timestamp=datetime(2026, 1, 1, 12, 0), onchain=SAFE_ONCHAIN, social=SAFE_SOCIAL))
    history.scans.append(ScanRecord(timestamp=datetime(2026, 1, 1, 12, 20), onchain=DANGER_ONCHAIN, social=SAFE_SOCIAL))
    # only one passing scan now -> not confirmed, even though two scans happened
    assert not history.is_confirmed(required_scans=2, gap_minutes=15)


def test_flip_to_danger_after_being_safe_is_caught_on_next_scan():
    """Simulates a token that looked safe, then had liquidity pulled or
    authority changed before the reconfirmation window closed."""
    history = CandidateHistory("TOKEN")
    history.scans.append(ScanRecord(timestamp=datetime(2026, 1, 1, 12, 0), onchain=SAFE_ONCHAIN, social=SAFE_SOCIAL))
    later = ScanRecord(timestamp=datetime(2026, 1, 1, 12, 20), onchain=DANGER_ONCHAIN, social=SAFE_SOCIAL)
    history.scans.append(later)
    assert not later.passed
    assert not history.is_confirmed(required_scans=2, gap_minutes=15)
