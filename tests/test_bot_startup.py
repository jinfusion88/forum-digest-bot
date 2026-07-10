from datetime import datetime, timezone, timedelta
from db import Database, PendingAnnouncement
from bot import reconcile_on_startup
from config import Config

class FakeGateway:
    def __init__(self):
        self.backfilled_forums = []
        self.processed_guilds = []

    async def list_active_and_recent_archived_threads(self, forum_channel_id):
        self.backfilled_forums.append(forum_channel_id)
        return []

    async def fetch_messages_since(self, thread_id, since, cap):
        return []

    async def thread_exists_and_accessible(self, thread_id):
        return True

    async def post_new_thread_announcement(self, forum_channel_id, thread_id):
        pass

    async def send_admin_notice(self, guild_id, text):
        pass

async def test_reconcile_backfills_every_monitored_forum(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    await db.add_monitored_forum(20, guild_id=1, designated_at=now)
    gateway = FakeGateway()
    await reconcile_on_startup(db, gateway, guild_id=1, config=Config())
    assert set(gateway.backfilled_forums) == {10, 20}

async def test_reconcile_resumes_pending_announcements(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_pending_announcement(
        PendingAnnouncement(thread_id=1, forum_channel_id=10, guild_id=1, due_at=now - timedelta(minutes=5), posted=False)
    )
    gateway = FakeGateway()
    posted = []
    gateway.post_new_thread_announcement = lambda f, t: posted.append((f, t)) or _async_noop()
    await reconcile_on_startup(db, gateway, guild_id=1, config=Config())
    assert await db.get_unposted_announcements(guild_id=1) == []

def _async_noop():
    import asyncio
    async def noop():
        return None
    return noop()
