from memebot.config import SafetyConfig
from memebot.models import OnchainReport, Verdict
from memebot.safety.onchain import evaluate_onchain_safety, merge_reports


def safe_report(**overrides):
    defaults = dict(
        token_address="TOKEN",
        mint_authority_renounced=True,
        freeze_authority_renounced=True,
        lp_locked_or_burned=True,
        lp_locked_pct=100.0,
        top10_holder_pct=15.0,
        single_largest_holder_pct=5.0,
        holder_count=500,
        buy_tax_pct=0.0,
        sell_tax_pct=0.0,
        is_honeypot=False,
        rugcheck_risk_score=100.0,
        goplus_confidence=1.0,
    )
    defaults.update(overrides)
    return OnchainReport(**defaults)


def test_all_clean_report_is_safe():
    result = evaluate_onchain_safety(safe_report(), SafetyConfig())
    assert result.verdict == Verdict.SAFE


def test_mint_authority_not_renounced_is_danger():
    result = evaluate_onchain_safety(safe_report(mint_authority_renounced=False), SafetyConfig())
    assert result.verdict == Verdict.DANGER
    assert any("Mint authority" in r for r in result.reasons)


def test_honeypot_flag_is_danger():
    result = evaluate_onchain_safety(safe_report(is_honeypot=True), SafetyConfig())
    assert result.verdict == Verdict.DANGER


def test_unlocked_liquidity_is_danger():
    result = evaluate_onchain_safety(safe_report(lp_locked_or_burned=False), SafetyConfig())
    assert result.verdict == Verdict.DANGER


def test_high_holder_concentration_is_danger():
    result = evaluate_onchain_safety(safe_report(top10_holder_pct=45.0), SafetyConfig())
    assert result.verdict == Verdict.DANGER


def test_unknown_mint_authority_is_warn_not_safe():
    result = evaluate_onchain_safety(safe_report(mint_authority_renounced=None), SafetyConfig())
    assert result.verdict == Verdict.WARN


def test_missing_data_never_defaults_to_safe():
    empty = OnchainReport(
        token_address="TOKEN",
        mint_authority_renounced=None,
        freeze_authority_renounced=None,
        lp_locked_or_burned=None,
        lp_locked_pct=None,
        top10_holder_pct=None,
        single_largest_holder_pct=None,
        holder_count=None,
        buy_tax_pct=None,
        sell_tax_pct=None,
        is_honeypot=None,
        rugcheck_risk_score=None,
        goplus_confidence=None,
    )
    result = evaluate_onchain_safety(empty, SafetyConfig())
    assert result.verdict != Verdict.SAFE


def test_merge_reports_disagreement_favors_caution():
    rugcheck_fields = {"mint_authority_renounced": True}
    goplus_fields = {"mint_authority_renounced": False}
    merged = merge_reports(rugcheck_fields, goplus_fields, "TOKEN")
    assert merged.mint_authority_renounced is False


def test_merge_reports_honeypot_from_either_source_wins():
    rugcheck_fields = {"is_honeypot": False}
    goplus_fields = {"is_honeypot": True}
    merged = merge_reports(rugcheck_fields, goplus_fields, "TOKEN")
    assert merged.is_honeypot is True
