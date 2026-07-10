from datetime import datetime, timedelta


def is_stale(due_at: datetime, now: datetime, staleness_cap_hours: int) -> bool:
    return now - due_at > timedelta(hours=staleness_cap_hours)
