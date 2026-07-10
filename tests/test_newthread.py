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


from db import Database, PendingAnnouncement
from newthread import NewThreadAnnouncer

class FakeNewThreadGateway:
    def __init__(self, existing_thread_ids=None):
        self.existing_thread_ids = existing_thread_ids or set()
        self.posted = []
        self.admin_notices = []

    async def thread_exists_and_accessible(self, thread_id):
        return thread_id in self.existing_thread_ids

    async def post_new_thread_announcement(self, forum_channel_id, thread_id):
        self.posted.append((forum_channel_id, thread_id))

    async def send_admin_notice(self, guild_id, text):
        self.admin_notices.append(text)

async def test_register_new_thread_creates_pending_row(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
    gateway = FakeNewThreadGateway()
    announcer = NewThreadAnnouncer(db, gateway)
    await announcer.register_new_thread(thread_id=1, forum_channel_id=10, guild_id=1, now=now, delay_minutes=60)
    pending = await db.get_unposted_announcements(guild_id=1)
    assert len(pending) == 1
    assert pending[0].due_at == now + timedelta(minutes=60)

async def test_process_due_announcement_posts_when_not_yet_due_is_false(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
    await db.add_pending_announcement(
        PendingAnnouncement(1, 10, guild_id=1, due_at=now - timedelta(minutes=1), posted=False)
    )
    gateway = FakeNewThreadGateway(existing_thread_ids={1})
    announcer = NewThreadAnnouncer(db, gateway)
    await announcer.process_due_announcements(guild_id=1, now=now, staleness_cap_hours=24)
    assert gateway.posted == [(10, 1)]
    assert await db.get_unposted_announcements(guild_id=1) == []

async def test_process_due_announcement_skips_deleted_thread_silently(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
    await db.add_pending_announcement(
        PendingAnnouncement(1, 10, guild_id=1, due_at=now - timedelta(minutes=1), posted=False)
    )
    gateway = FakeNewThreadGateway(existing_thread_ids=set())
    announcer = NewThreadAnnouncer(db, gateway)
    await announcer.process_due_announcements(guild_id=1, now=now, staleness_cap_hours=24)
    assert gateway.posted == []
    assert gateway.admin_notices == []
    assert await db.get_unposted_announcements(guild_id=1) == []

async def test_process_due_announcement_skips_and_notifies_admin_when_stale(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
    await db.add_pending_announcement(
        PendingAnnouncement(1, 10, guild_id=1, due_at=now - timedelta(hours=48), posted=False)
    )
    gateway = FakeNewThreadGateway(existing_thread_ids={1})
    announcer = NewThreadAnnouncer(db, gateway)
    await announcer.process_due_announcements(guild_id=1, now=now, staleness_cap_hours=24)
    assert gateway.posted == []
    assert len(gateway.admin_notices) == 1
    assert await db.get_unposted_announcements(guild_id=1) == []

async def test_process_due_announcement_ignores_not_yet_due_rows(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
    await db.add_pending_announcement(
        PendingAnnouncement(1, 10, guild_id=1, due_at=now + timedelta(minutes=30), posted=False)
    )
    gateway = FakeNewThreadGateway(existing_thread_ids={1})
    announcer = NewThreadAnnouncer(db, gateway)
    await announcer.process_due_announcements(guild_id=1, now=now, staleness_cap_hours=24)
    assert gateway.posted == []
    remaining = await db.get_unposted_announcements(guild_id=1)
    assert len(remaining) == 1

async def test_process_due_announcements_scoped_to_guild(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, 10, 0, tzinfo=timezone.utc)
    await db.add_pending_announcement(
        PendingAnnouncement(1, 10, guild_id=1, due_at=now - timedelta(minutes=1), posted=False)
    )
    await db.add_pending_announcement(
        PendingAnnouncement(2, 20, guild_id=2, due_at=now - timedelta(minutes=1), posted=False)
    )
    gateway = FakeNewThreadGateway(existing_thread_ids={1, 2})
    announcer = NewThreadAnnouncer(db, gateway)
    await announcer.process_due_announcements(guild_id=1, now=now, staleness_cap_hours=24)
    assert gateway.posted == [(10, 1)]
    assert len(await db.get_unposted_announcements(guild_id=2)) == 1
