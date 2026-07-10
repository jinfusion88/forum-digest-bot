# tests/test_forum_tracking.py
from datetime import datetime, timezone
from db import Database
from newthread import NewThreadAnnouncer
from cogs.forum_tracking import ForumTrackingCog
from config import Config

class FakeParent:
    def __init__(self, id):
        self.id = id

class FakeThread:
    def __init__(self, id, parent_id, guild_id=1, created_at=None):
        self.id = id
        self.parent_id = parent_id
        self.guild = type("G", (), {"id": guild_id})()
        self.created_at = created_at or datetime.now(timezone.utc)

class FakeAuthor:
    def __init__(self, id, bot=False):
        self.id = id
        self.bot = bot

class FakeMessage:
    def __init__(self, id, channel, author_id, bot_author=False):
        self.id = id
        self.channel = channel
        self.author = FakeAuthor(author_id, bot=bot_author)

class FakeGateway:
    def __init__(self):
        self.registered = []

class FakeAnnouncer:
    def __init__(self):
        self.registered = []

    async def register_new_thread(self, thread_id, forum_channel_id, guild_id, now, delay_minutes):
        self.registered.append((thread_id, forum_channel_id))

async def test_on_thread_create_registers_announcement_for_monitored_forum(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    announcer = FakeAnnouncer()
    cog = ForumTrackingCog(db, announcer, Config())
    thread = FakeThread(id=100, parent_id=10)
    await cog.on_thread_create(thread)
    assert announcer.registered == [(100, 10)]

async def test_on_thread_create_ignores_unmonitored_forum(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    announcer = FakeAnnouncer()
    cog = ForumTrackingCog(db, announcer, Config())
    thread = FakeThread(id=100, parent_id=999)  # not monitored
    await cog.on_thread_create(thread)
    assert announcer.registered == []

async def test_on_message_records_activity_for_monitored_forum_thread(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    announcer = FakeAnnouncer()
    cog = ForumTrackingCog(db, announcer, Config())
    thread = FakeThread(id=100, parent_id=10)
    message = FakeMessage(id=1, channel=thread, author_id=555)
    await cog.on_message(message)
    activity = await db.get_thread_activity(100)
    assert activity.message_count == 1

async def test_on_message_ignores_bot_authors(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    announcer = FakeAnnouncer()
    cog = ForumTrackingCog(db, announcer, Config())
    thread = FakeThread(id=100, parent_id=10)
    message = FakeMessage(id=1, channel=thread, author_id=555, bot_author=True)
    await cog.on_message(message)
    activity = await db.get_thread_activity(100)
    assert activity is None
