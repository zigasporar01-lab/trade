"""On-chain rug-pull screen. Pure function: report fields in, verdict out.

Philosophy: default to DANGER on missing data. A token we can't verify is
not a token we trade — "unknown" is never treated as "safe". Any single
hard red flag (honeypot, un-renounced mint authority, unlocked LP) is an
immediate DANGER regardless of everything else looking fine.
"""

from __future__ import annotations

from memebot.config import SafetyConfig
from memebot.models import OnchainReport, SafetyResult, Verdict


def evaluate_onchain_safety(report: OnchainReport, cfg: SafetyConfig) -> SafetyResult:
    reasons: list[str] = []
    danger = False
    warn = False

    def require_true(value: bool | None, flag_enabled: bool, danger_msg: str, unknown_msg: str) -> None:
        nonlocal danger, warn
        if not flag_enabled:
            return
        if value is None:
            warn = True
            reasons.append(unknown_msg)
        elif value is False:
            danger = True
            reasons.append(danger_msg)

    require_true(
        report.mint_authority_renounced,
        cfg.require_mint_authority_renounced,
        "Mint authority is NOT renounced — creator can mint unlimited new supply.",
        "Mint authority status unknown.",
    )
    require_true(
        report.freeze_authority_renounced,
        cfg.require_freeze_authority_renounced,
        "Freeze authority is NOT renounced — creator can freeze your tokens.",
        "Freeze authority status unknown.",
    )
    require_true(
        report.lp_locked_or_burned,
        cfg.require_lp_locked_or_burned,
        "Liquidity is NOT locked or burned — creator can pull liquidity at any time.",
        "LP lock status unknown.",
    )

    if report.is_honeypot is True and cfg.reject_on_honeypot_flag:
        danger = True
        reasons.append("Flagged as a honeypot — token may be unsellable.")
    elif report.is_honeypot is None:
        warn = True
        reasons.append("Honeypot status unknown.")

    if report.lp_locked_pct is not None and report.lp_locked_pct < cfg.min_lp_locked_pct:
        danger = True
        reasons.append(
            f"Only {report.lp_locked_pct:.1f}% of LP is locked (need >= {cfg.min_lp_locked_pct}%)."
        )

    if report.top10_holder_pct is not None:
        if report.top10_holder_pct > cfg.max_top10_holder_pct:
            danger = True
            reasons.append(
                f"Top 10 holders own {report.top10_holder_pct:.1f}% of supply "
                f"(max allowed {cfg.max_top10_holder_pct}%) — high dump risk."
            )
    else:
        warn = True
        reasons.append("Holder concentration unknown.")

    if report.single_largest_holder_pct is not None and report.single_largest_holder_pct > cfg.max_single_holder_pct:
        danger = True
        reasons.append(
            f"Largest single holder owns {report.single_largest_holder_pct:.1f}% "
            f"(max allowed {cfg.max_single_holder_pct}%)."
        )

    if report.buy_tax_pct is not None and report.buy_tax_pct > cfg.max_buy_tax_pct:
        danger = True
        reasons.append(f"Buy tax {report.buy_tax_pct:.1f}% exceeds max {cfg.max_buy_tax_pct}%.")
    if report.sell_tax_pct is not None and report.sell_tax_pct > cfg.max_sell_tax_pct:
        danger = True
        reasons.append(f"Sell tax {report.sell_tax_pct:.1f}% exceeds max {cfg.max_sell_tax_pct}% (soft honeypot risk).")

    if report.rugcheck_risk_score is not None and report.rugcheck_risk_score > cfg.max_rugcheck_risk_score:
        danger = True
        reasons.append(
            f"RugCheck risk score {report.rugcheck_risk_score:.0f} exceeds max {cfg.max_rugcheck_risk_score:.0f}."
        )

    if report.goplus_confidence is not None and report.goplus_confidence < cfg.min_goplus_confidence:
        warn = True
        reasons.append(f"GoPlus data confidence low ({report.goplus_confidence:.2f}).")

    if danger:
        verdict = Verdict.DANGER
    elif warn:
        verdict = Verdict.WARN
    else:
        verdict = Verdict.SAFE
        reasons.append("All on-chain safety checks passed.")

    return SafetyResult(verdict=verdict, reasons=reasons, report=report)


def merge_reports(rugcheck_fields: dict, goplus_fields: dict, token_address: str) -> OnchainReport:
    """Merge two independent sources. On disagreement over a boolean safety
    flag, the more cautious (False/unsafe) value always wins.
    """

    def pick_bool_cautious(a, b):
        vals = [v for v in (a, b) if v is not None]
        if not vals:
            return None
        return all(vals)  # both must say "renounced/safe" for us to trust it

    def pick_bool_permissive_danger(a, b):
        vals = [v for v in (a, b) if v is not None]
        if not vals:
            return None
        return any(vals)  # either source flagging honeypot=True is enough

    def pick_max(a, b):
        vals = [v for v in (a, b) if v is not None]
        return max(vals) if vals else None

    def pick_first(a, b):
        return a if a is not None else b

    return OnchainReport(
        token_address=token_address,
        mint_authority_renounced=pick_bool_cautious(
            rugcheck_fields.get("mint_authority_renounced"), goplus_fields.get("mint_authority_renounced")
        ),
        freeze_authority_renounced=pick_bool_cautious(
            rugcheck_fields.get("freeze_authority_renounced"), goplus_fields.get("freeze_authority_renounced")
        ),
        lp_locked_or_burned=pick_bool_cautious(rugcheck_fields.get("lp_locked_or_burned"), None),
        lp_locked_pct=pick_first(rugcheck_fields.get("lp_locked_pct"), None),
        top10_holder_pct=pick_max(rugcheck_fields.get("top10_holder_pct"), goplus_fields.get("top10_holder_pct")),
        single_largest_holder_pct=pick_first(rugcheck_fields.get("single_largest_holder_pct"), None),
        holder_count=pick_first(rugcheck_fields.get("holder_count"), None),
        buy_tax_pct=pick_max(rugcheck_fields.get("buy_tax_pct"), goplus_fields.get("buy_tax_pct")),
        sell_tax_pct=pick_max(rugcheck_fields.get("sell_tax_pct"), goplus_fields.get("sell_tax_pct")),
        is_honeypot=pick_bool_permissive_danger(rugcheck_fields.get("is_honeypot"), goplus_fields.get("is_honeypot")),
        rugcheck_risk_score=rugcheck_fields.get("rugcheck_risk_score"),
        goplus_confidence=goplus_fields.get("goplus_confidence"),
        raw_sources={"rugcheck": rugcheck_fields, "goplus": goplus_fields},
    )
