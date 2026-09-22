from datetime import datetime, timedelta

from memebot.config import SocialConfig
from memebot.models import SocialMention
from memebot.safety.social import build_social_report, evaluate_social_safety

NOW = datetime(2026, 1, 1)


def make_mention(author_id, text="great project", age_days=100, followers=200):
    return SocialMention(
        author_id=author_id,
        author_handle=f"user_{author_id}",
        author_created_at=NOW - timedelta(days=age_days),
        author_followers=followers,
        text=text,
        created_at=NOW - timedelta(hours=1),
    )


def test_organic_looking_activity_is_safe():
    mentions = [make_mention(str(i), text=f"looking solid, holding #{i}") for i in range(10)]
    cfg = SocialConfig()
    report = build_social_report("TOKEN", mentions, cfg)
    result = evaluate_social_safety(report, cfg)
    assert result.verdict != "DANGER"


def test_too_few_mentions_is_warn():
    mentions = [make_mention("1")]
    cfg = SocialConfig(min_mentions_24h=5, min_unique_authors_24h=3)
    report = build_social_report("TOKEN", mentions, cfg)
    result = evaluate_social_safety(report, cfg)
    assert result.verdict.value == "WARN"


def test_mostly_new_accounts_is_danger():
    mentions = [make_mention(str(i), age_days=1) for i in range(10)]
    cfg = SocialConfig(max_new_account_ratio=0.6, min_account_age_days=14)
    report = build_social_report("TOKEN", mentions, cfg)
    result = evaluate_social_safety(report, cfg)
    assert result.verdict.value == "DANGER"


def test_negative_sentiment_flood_is_danger():
    mentions = [make_mention(str(i), text="this is a rug, avoid, scam") for i in range(10)]
    cfg = SocialConfig(max_negative_sentiment_ratio=0.6)
    report = build_social_report("TOKEN", mentions, cfg)
    result = evaluate_social_safety(report, cfg)
    assert result.verdict.value == "DANGER"


def test_duplicate_promo_text_cluster_is_danger():
    mentions = [make_mention(str(i), text="🚀🚀 BUY NOW BEFORE ITS TOO LATE 🚀🚀 LFG") for i in range(10)]
    cfg = SocialConfig()
    report = build_social_report("TOKEN", mentions, cfg)
    result = evaluate_social_safety(report, cfg)
    assert result.verdict.value == "DANGER"


def test_disabled_social_screening_never_returns_safe():
    cfg = SocialConfig(enabled=False)
    report = build_social_report("TOKEN", [], cfg)
    result = evaluate_social_safety(report, cfg)
    assert result.verdict.value == "WARN"
