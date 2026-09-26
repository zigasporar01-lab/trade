from memebot.core.spend_tracker import SpendTracker


def test_fresh_tracker_starts_at_zero(tmp_path):
    tracker = SpendTracker(tmp_path / "spend.json")
    assert tracker.spent_today() == 0.0
    assert tracker.budget_exceeded(2.0) is False


def test_record_reads_accumulates_estimated_cost(tmp_path):
    tracker = SpendTracker(tmp_path / "spend.json")
    tracker.record_reads(post_count=10, profile_count=5)  # 10*0.005 + 5*0.010 = 0.10
    assert abs(tracker.spent_today() - 0.10) < 1e-9

    tracker.record_reads(post_count=10, profile_count=5)
    assert abs(tracker.spent_today() - 0.20) < 1e-9


def test_budget_exceeded_once_spend_reaches_cap(tmp_path):
    tracker = SpendTracker(tmp_path / "spend.json")
    tracker.record_reads(post_count=100, profile_count=100)  # 0.5 + 1.0 = 1.5
    assert tracker.budget_exceeded(1.5) is True
    assert tracker.budget_exceeded(2.0) is False


def test_none_budget_never_exceeded(tmp_path):
    tracker = SpendTracker(tmp_path / "spend.json")
    tracker.record_reads(post_count=1000, profile_count=1000)
    assert tracker.budget_exceeded(None) is False


def test_spend_persists_across_a_new_tracker_instance_same_day(tmp_path):
    path = tmp_path / "spend.json"
    SpendTracker(path).record_reads(post_count=10, profile_count=10)

    reloaded = SpendTracker(path)
    assert abs(reloaded.spent_today() - 0.15) < 1e-9  # 10*0.005 + 10*0.010


def test_spend_resets_when_stored_day_differs_from_today(tmp_path):
    import json

    path = tmp_path / "spend.json"
    path.write_text(json.dumps({"day": "2000-01-01", "spend_usd": 999.0}))

    tracker = SpendTracker(path)
    assert tracker.spent_today() == 0.0  # stale day discarded, not carried over


def test_corrupt_file_is_treated_as_zero_spend_not_a_crash(tmp_path):
    path = tmp_path / "spend.json"
    path.write_text("{not valid json")

    tracker = SpendTracker(path)
    assert tracker.spent_today() == 0.0
