import pytest
from datetime import datetime, timezone
from db import Database, GuildConfig, ThreadActivity, PendingAnnouncement

@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()

@pytest.mark.asyncio
async def test_guild_config_defaults_to_none_fields(db):
    cfg = await db.get_guild_config(111)
    assert cfg == GuildConfig(111, None, None, None, None, None)

@pytest.mark.asyncio
async def test_set_digest_channel_persists(db):
    await db.set_digest_channel(111, 222)
    cfg = await db.get_guild_config(111)
    assert cfg.digest_channel_id == 222

@pytest.mark.asyncio
async def test_record_message_creates_and_increments_activity(db):
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=100)
    await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=101)
    await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=100)
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 3
    assert activity.unique_participant_count == 2

@pytest.mark.asyncio
async def test_reset_guild_activity_clears_counters_but_keeps_last_featured(db):
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=100)
    await db.set_last_featured(1, now)
    await db.add_monitored_forum(10, guild_id=999, designated_at=now)
    await db.reset_guild_activity(999)
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 0
    assert activity.unique_participant_count == 0
    assert activity.last_featured_at == now

@pytest.mark.asyncio
async def test_pending_announcement_roundtrip(db):
    due = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    await db.add_pending_announcement(PendingAnnouncement(thread_id=5, forum_channel_id=10, due_at=due, posted=False))
    unposted = await db.get_unposted_announcements()
    assert len(unposted) == 1
    assert unposted[0].thread_id == 5
    await db.mark_announcement_posted(5)
    assert await db.get_unposted_announcements() == []
