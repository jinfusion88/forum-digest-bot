import random
from datetime import datetime, timedelta
from db import ThreadActivity


def is_eligible(activity: ThreadActivity, min_messages: int, min_participants: int) -> bool:
    return (
        activity.message_count >= min_messages
        and activity.unique_participant_count >= min_participants
    )


def is_in_cooldown(activity: ThreadActivity, now: datetime, cooldown_days: int) -> bool:
    if activity.last_featured_at is None:
        return False
    return now - activity.last_featured_at < timedelta(days=cooldown_days)


def select_featured(
    candidates: list[ThreadActivity],
    now: datetime,
    cooldown_days: int,
    min_messages: int,
    min_participants: int,
    max_featured: int,
    rng: random.Random,
) -> list[ThreadActivity]:
    eligible = [
        a for a in candidates
        if is_eligible(a, min_messages, min_participants)
        and not is_in_cooldown(a, now, cooldown_days)
    ]
    eligible.sort(key=lambda a: (a.unique_participant_count, a.message_count), reverse=True)
    top = eligible[:max_featured]
    rng.shuffle(top)
    return top


def apply_new_thread_boost(activity: ThreadActivity, boost_messages: int) -> ThreadActivity:
    if activity.is_new_thread_boosted:
        return activity
    activity.message_count += boost_messages
    activity.is_new_thread_boosted = True
    return activity
