import random
from datetime import datetime, timedelta, timezone
from db import ThreadActivity
from scoring import is_eligible, is_in_cooldown, select_featured, apply_new_thread_boost

def make_activity(thread_id, messages, participants, last_featured_at=None):
    return ThreadActivity(
        thread_id=thread_id, forum_channel_id=1, created_at=None,
        message_count=messages, unique_participant_count=participants,
        reaction_count=0, is_new_thread_boosted=False,
        last_featured_at=last_featured_at, counted_capped=False,
    )

def test_eligible_at_exact_threshold():
    a = make_activity(1, messages=5, participants=3)
    assert is_eligible(a, min_messages=5, min_participants=3) is True

def test_ineligible_one_below_participant_threshold():
    a = make_activity(1, messages=10, participants=2)
    assert is_eligible(a, min_messages=5, min_participants=3) is False

def test_ineligible_one_below_message_threshold():
    a = make_activity(1, messages=4, participants=5)
    assert is_eligible(a, min_messages=5, min_participants=3) is False

def test_two_person_high_volume_does_not_qualify_over_broader_thread():
    high_volume_two_person = make_activity(1, messages=50, participants=2)
    broader_thread = make_activity(2, messages=6, participants=4)
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    selected = select_featured(
        [high_volume_two_person, broader_thread], now=now, cooldown_days=7,
        min_messages=5, min_participants=3, max_featured=5, rng=random.Random(0),
    )
    ids = {a.thread_id for a in selected}
    assert ids == {2}

def test_cooldown_excludes_recently_featured_thread():
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    featured_3_days_ago = now - timedelta(days=3)
    a = make_activity(1, messages=10, participants=5, last_featured_at=featured_3_days_ago)
    assert is_in_cooldown(a, now=now, cooldown_days=7) is True

def test_cooldown_expired_after_window():
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    featured_8_days_ago = now - timedelta(days=8)
    a = make_activity(1, messages=10, participants=5, last_featured_at=featured_8_days_ago)
    assert is_in_cooldown(a, now=now, cooldown_days=7) is False

def test_select_featured_caps_at_max_and_sorts_by_broadest_participation():
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    candidates = [
        make_activity(1, messages=6, participants=3),
        make_activity(2, messages=6, participants=8),
        make_activity(3, messages=6, participants=6),
        make_activity(4, messages=6, participants=5),
        make_activity(5, messages=6, participants=4),
        make_activity(6, messages=6, participants=9),
    ]
    selected = select_featured(
        candidates, now=now, cooldown_days=7, min_messages=5, min_participants=3,
        max_featured=5, rng=random.Random(0),
    )
    assert len(selected) == 5
    assert {a.thread_id for a in selected} == {2, 3, 4, 5, 6}

def test_select_featured_excludes_cooldown_thread_even_if_eligible():
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    on_cooldown = make_activity(1, messages=10, participants=10, last_featured_at=now - timedelta(days=1))
    eligible = make_activity(2, messages=5, participants=3)
    selected = select_featured(
        [on_cooldown, eligible], now=now, cooldown_days=7, min_messages=5,
        min_participants=3, max_featured=5, rng=random.Random(0),
    )
    assert {a.thread_id for a in selected} == {2}

def test_apply_new_thread_boost_adds_to_message_count():
    a = make_activity(1, messages=0, participants=0)
    boosted = apply_new_thread_boost(a, boost_messages=2)
    assert boosted.message_count == 2
    assert boosted.is_new_thread_boosted is True

def test_apply_new_thread_boost_is_idempotent():
    a = make_activity(1, messages=0, participants=0)
    a.is_new_thread_boosted = True
    boosted = apply_new_thread_boost(a, boost_messages=2)
    assert boosted.message_count == 0
