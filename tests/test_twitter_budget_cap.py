"""Verifies TwitterClient stops making paid search calls once the configured
daily budget is estimated spent, and correctly records real read counts
after a call that does go through.
"""

from unittest.mock import MagicMock

from memebot.core.spend_tracker import SpendTracker
from memebot.data.twitter import TwitterClient


def make_client(tmp_path, daily_budget_usd):
    tracker = SpendTracker(tmp_path / "spend.json")
    client = TwitterClient(
        bearer_token="fake-token",
        spend_tracker=tracker,
        daily_budget_usd=daily_budget_usd,
    )
    return client, tracker


def test_search_is_skipped_once_budget_already_exceeded(tmp_path):
    client, tracker = make_client(tmp_path, daily_budget_usd=1.0)
    tracker.record_reads(post_count=1000, profile_count=1000)  # way over $1

    client._search_recent = MagicMock()  # would fail the test if called

    mentions = client.search_token_mentions(symbol="FOO", token_address="TOKEN")

    assert mentions == []
    client._search_recent.assert_not_called()


def test_search_proceeds_and_records_spend_when_under_budget(tmp_path):
    client, tracker = make_client(tmp_path, daily_budget_usd=5.0)
    client._search_recent = MagicMock(
        return_value={
            "data": [
                {"author_id": "1", "created_at": "2026-01-01T00:00:00.000Z", "text": "hi", "public_metrics": {}},
                {"author_id": "2", "created_at": "2026-01-01T00:00:00.000Z", "text": "hi", "public_metrics": {}},
            ],
            "includes": {
                "users": [
                    {"id": "1", "username": "a", "created_at": "2020-01-01T00:00:00.000Z", "public_metrics": {}},
                    {"id": "2", "username": "b", "created_at": "2020-01-01T00:00:00.000Z", "public_metrics": {}},
                ]
            },
        }
    )

    mentions = client.search_token_mentions(symbol="FOO", token_address="TOKEN")

    assert len(mentions) == 2
    client._search_recent.assert_called_once()
    expected_cost = 2 * 0.005 + 2 * 0.010  # 2 posts + 2 profiles
    assert abs(tracker.spent_today() - expected_cost) < 1e-9


def test_no_budget_configured_never_blocks_search(tmp_path):
    client, tracker = make_client(tmp_path, daily_budget_usd=None)
    tracker.record_reads(post_count=100000, profile_count=100000)  # huge spend, no cap set

    client._search_recent = MagicMock(return_value={"data": [], "includes": {}})

    client.search_token_mentions(symbol="FOO", token_address="TOKEN")

    client._search_recent.assert_called_once()


def test_client_without_a_spend_tracker_behaves_exactly_as_before(tmp_path):
    client = TwitterClient(bearer_token="fake-token")  # no tracker passed at all
    client._search_recent = MagicMock(return_value={"data": [], "includes": {}})

    client.search_token_mentions(symbol="FOO", token_address="TOKEN")

    client._search_recent.assert_called_once()
