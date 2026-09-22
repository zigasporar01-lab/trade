"""Social/X due-diligence screen.

Goal isn't to predict price from hype — it's to catch the two failure modes
that precede most memecoin scams:
  1. Silence: nobody organic is talking about it (can't verify it's real).
  2. Coordinated pump: mentions exist but come from a cluster of brand-new,
     low-follower accounts posting near-identical text (classic bot-pump
     that precedes a coordinated sell/rug).

A crude sentiment heuristic (keyword-based, no external NLP dependency) flags
when the token's own community is already screaming "rug"/"scam"/"can't sell".
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from memebot.config import SocialConfig
from memebot.models import SocialMention, SocialReport, SocialResult, Verdict

NEGATIVE_KEYWORDS = (
    "rug",
    "rugged",
    "scam",
    "honeypot",
    "can't sell",
    "cant sell",
    "unable to sell",
    "avoid",
    "warning",
    "exit scam",
    "dumped",
)


def _is_negative(text: str) -> bool:
    lowered = text.lower()
    return any(kw in lowered for kw in NEGATIVE_KEYWORDS)


def build_social_report(token_address: str, mentions: list[SocialMention], cfg: SocialConfig) -> SocialReport:
    now = datetime.utcnow()
    unique_authors = len({m.author_id for m in mentions})

    new_accounts = 0
    known_age = 0
    for m in mentions:
        if m.author_created_at is None:
            continue
        known_age += 1
        age_days = (now - m.author_created_at).days
        if age_days < cfg.min_account_age_days:
            new_accounts += 1
    new_account_ratio = (new_accounts / known_age) if known_age else 0.0

    negative = sum(1 for m in mentions if _is_negative(m.text))
    negative_ratio = (negative / len(mentions)) if mentions else 0.0

    return SocialReport(
        token_address=token_address,
        mentions=mentions,
        unique_authors=unique_authors,
        new_account_ratio=new_account_ratio,
        negative_sentiment_ratio=negative_ratio,
        fetched_at=now,
    )


def _detect_duplicate_text_cluster(mentions: list[SocialMention], threshold: float = 0.4) -> bool:
    """Flag near-identical copy-paste promo text across many distinct authors —
    a strong signature of a paid/botted pump campaign."""
    if len(mentions) < 5:
        return False
    normalized = Counter(m.text.strip().lower()[:80] for m in mentions)
    most_common_count = normalized.most_common(1)[0][1]
    return (most_common_count / len(mentions)) >= threshold


def evaluate_social_safety(report: SocialReport, cfg: SocialConfig) -> SocialResult:
    if not cfg.enabled:
        return SocialResult(verdict=Verdict.WARN, reasons=["Social screening disabled in config."], report=report)

    reasons: list[str] = []
    danger = False
    warn = False

    if report.unique_authors < cfg.min_unique_authors_24h:
        warn = True
        reasons.append(
            f"Only {report.unique_authors} unique accounts mentioning this token "
            f"(need >= {cfg.min_unique_authors_24h}) — can't verify organic interest."
        )

    if len(report.mentions) < cfg.min_mentions_24h:
        warn = True
        reasons.append(
            f"Only {len(report.mentions)} mentions in the last 24h (need >= {cfg.min_mentions_24h})."
        )

    if report.new_account_ratio > cfg.max_new_account_ratio:
        danger = True
        reasons.append(
            f"{report.new_account_ratio:.0%} of mentions are from accounts younger than "
            f"{cfg.min_account_age_days} days — looks like a coordinated/bot pump."
        )

    if report.negative_sentiment_ratio > cfg.max_negative_sentiment_ratio:
        danger = True
        reasons.append(
            f"{report.negative_sentiment_ratio:.0%} of mentions contain rug/scam-warning language."
        )

    if _detect_duplicate_text_cluster(report.mentions):
        danger = True
        reasons.append("Large cluster of near-identical promotional text detected across authors.")

    if danger:
        verdict = Verdict.DANGER
    elif warn:
        verdict = Verdict.WARN
    else:
        verdict = Verdict.SAFE
        reasons.append("Social activity looks organic; no coordinated-pump or rug-warning signals.")

    return SocialResult(verdict=verdict, reasons=reasons, report=report)
