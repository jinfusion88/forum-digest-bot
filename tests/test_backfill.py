# tests/test_backfill.py
from datetime import datetime, timedelta, timezone
from db import Database, ThreadActivity
from backfill import backfill_forum, DiscoveredThread, BackfillMessage
from config import Config

class FakeBackfillGateway:
    def __init__(self, threads, messages_by_thread):
        self.threads = threads
        self.messages_by_thread = messages_by_thread
        self.fetch_calls = []

    async def list_active_and_recent_archived_threads(self, forum_channel_id):
        return self.threads

    async def fetch_messages_since(self, thread_id, since, cap):
        self.fetch_calls.append((thread_id, since, cap))
        return self.messages_by_thread.get(thread_id, [])[:cap]

async def test_backfill_populates_activity_for_discovered_threads(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    threads = [DiscoveredThread(thread_id=1, created_at=now - timedelta(days=2))]
    messages = {1: [
        BackfillMessage(author_id=100, reaction_count=2),
        BackfillMessage(author_id=101, reaction_count=0),
        BackfillMessage(author_id=100, reaction_count=1),
    ]}
    gateway = FakeBackfillGateway(threads, messages)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now - timedelta(days=1))
    await backfill_forum(db, gateway, guild_id=1, forum_channel_id=10, config=Config(), now=now)
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 3
    assert activity.unique_participant_count == 2
    assert activity.reaction_count == 3

async def test_backfill_caps_message_fetch_and_marks_counted_capped(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    threads = [DiscoveredThread(thread_id=1, created_at=now - timedelta(days=2))]
    many_messages = [BackfillMessage(author_id=i % 5, reaction_count=0) for i in range(500)]
    gateway = FakeBackfillGateway(threads, {1: many_messages})
    await db.add_monitored_forum(10, guild_id=1, designated_at=now - timedelta(days=1))
    config = Config(backfill_message_cap=200)
    await backfill_forum(db, gateway, guild_id=1, forum_channel_id=10, config=config, now=now)
    assert gateway.fetch_calls[0][2] == 200
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 200
    assert activity.counted_capped is True

async def test_backfill_window_starts_at_later_of_last_digest_or_designation(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    designated_at = now - timedelta(days=5)
    last_digest_at = now - timedelta(days=2)
    await db.add_monitored_forum(10, guild_id=1, designated_at=designated_at)
    await db.set_last_digest_at(1, last_digest_at)
    gateway = FakeBackfillGateway([DiscoveredThread(thread_id=1, created_at=now - timedelta(days=4))], {1: []})
    await backfill_forum(db, gateway, guild_id=1, forum_channel_id=10, config=Config(), now=now)
    assert gateway.fetch_calls[0][1] == last_digest_at

async def test_backfill_does_not_create_pending_new_thread_announcements(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now - timedelta(days=1))
    gateway = FakeBackfillGateway([DiscoveredThread(thread_id=1, created_at=now - timedelta(days=2))], {1: []})
    await backfill_forum(db, gateway, guild_id=1, forum_channel_id=10, config=Config(), now=now)
    assert await db.get_unposted_announcements(guild_id=1) == []

async def test_backfill_preserves_last_featured_and_boost_across_restart(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    featured_at = now - timedelta(days=2)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now - timedelta(days=5))
    await db.upsert_thread_activity(ThreadActivity(
        thread_id=1, forum_channel_id=10, created_at=now - timedelta(days=4),
        message_count=6, unique_participant_count=3, reaction_count=0,
        is_new_thread_boosted=True, last_featured_at=featured_at, counted_capped=False,
    ))
    gateway = FakeBackfillGateway(
        [DiscoveredThread(thread_id=1, created_at=now - timedelta(days=4))],
        {1: [BackfillMessage(author_id=100, reaction_count=0)]},
    )
    await backfill_forum(db, gateway, guild_id=1, forum_channel_id=10, config=Config(), now=now)
    activity = await db.get_thread_activity(1)
    assert activity.last_featured_at == featured_at
    assert activity.is_new_thread_boosted is True
    # 1 fetched message + 2 boost (Config default new_thread_boost_messages)
    assert activity.message_count == 3
