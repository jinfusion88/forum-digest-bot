from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from config import Config
from db import Database, ThreadActivity


@dataclass
class DiscoveredThread:
    thread_id: int
    created_at: datetime


@dataclass
class BackfillMessage:
    author_id: int
    reaction_count: int


class BackfillGateway(Protocol):
    async def list_active_and_recent_archived_threads(self, forum_channel_id: int) -> list[DiscoveredThread]: ...
    async def fetch_messages_since(self, thread_id: int, since: datetime, cap: int) -> list[BackfillMessage]: ...


async def backfill_forum(
    db: Database,
    gateway: BackfillGateway,
    guild_id: int,
    forum_channel_id: int,
    config: Config,
    now: datetime,
) -> None:
    forums = await db.get_monitored_forums(guild_id)
    forum = next(f for f in forums if f.forum_channel_id == forum_channel_id)
    guild_config = await db.get_guild_config(guild_id)

    window_start = forum.designated_at
    if guild_config.last_digest_at is not None and guild_config.last_digest_at > window_start:
        window_start = guild_config.last_digest_at

    discovered = await gateway.list_active_and_recent_archived_threads(forum_channel_id)

    for thread in discovered:
        messages = await gateway.fetch_messages_since(thread.thread_id, window_start, config.backfill_message_cap)
        capped = len(messages) >= config.backfill_message_cap

        seen_participants = set()
        message_count = 0
        reaction_count = 0
        for m in messages:
            seen_participants.add(m.author_id)
            message_count += 1
            reaction_count += m.reaction_count

        activity = ThreadActivity(
            thread_id=thread.thread_id, forum_channel_id=forum_channel_id, created_at=thread.created_at,
            message_count=message_count, unique_participant_count=len(seen_participants),
            reaction_count=reaction_count, is_new_thread_boosted=False, last_featured_at=None,
            counted_capped=capped,
        )
        await db.upsert_thread_activity(activity)
        for user_id in seen_participants:
            await db.add_participant(thread.thread_id, user_id)
