from datetime import datetime, timedelta, timezone
from newthread import is_stale

def test_not_stale_within_cap():
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    due_at = now - timedelta(hours=2)
    assert is_stale(due_at, now, staleness_cap_hours=24) is False

def test_stale_beyond_cap():
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    due_at = now - timedelta(hours=25)
    assert is_stale(due_at, now, staleness_cap_hours=24) is True

def test_exactly_at_cap_is_not_yet_stale():
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    due_at = now - timedelta(hours=24)
    assert is_stale(due_at, now, staleness_cap_hours=24) is False
