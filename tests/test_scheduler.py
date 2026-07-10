from datetime import datetime
from zoneinfo import ZoneInfo
from scheduler import build_digest_cron_trigger

def test_fires_at_correct_local_time_before_dst_spring_forward():
    trigger = build_digest_cron_trigger(["monday", "friday"], "16:00", "America/Chicago")
    before = datetime(2026, 3, 6, 12, 0, tzinfo=ZoneInfo("America/Chicago"))  # Friday, before DST starts Mar 8
    next_fire = trigger.get_next_fire_time(None, before)
    assert next_fire.hour == 16
    assert next_fire.minute == 0
    assert next_fire.strftime("%A") == "Friday"

def test_fires_at_correct_local_time_after_dst_spring_forward():
    trigger = build_digest_cron_trigger(["monday", "friday"], "16:00", "America/Chicago")
    after = datetime(2026, 3, 9, 12, 0, tzinfo=ZoneInfo("America/Chicago"))  # Monday, after DST started Mar 8
    next_fire = trigger.get_next_fire_time(None, after)
    assert next_fire.hour == 16
    assert next_fire.minute == 0

def test_fires_at_correct_local_time_across_fall_back():
    trigger = build_digest_cron_trigger(["monday", "friday"], "16:00", "America/Chicago")
    before = datetime(2026, 11, 2, 12, 0, tzinfo=ZoneInfo("America/Chicago"))  # Monday, before fall-back Nov 1 (already passed)
    next_fire = trigger.get_next_fire_time(None, before)
    assert next_fire.hour == 16
    assert next_fire.minute == 0
    assert next_fire.tzinfo is not None

def test_only_configured_days_are_used():
    trigger = build_digest_cron_trigger(["monday"], "16:00", "America/Chicago")
    start = datetime(2026, 7, 9, 0, 0, tzinfo=ZoneInfo("America/Chicago"))  # a Thursday
    next_fire = trigger.get_next_fire_time(None, start)
    assert next_fire.strftime("%A") == "Monday"
