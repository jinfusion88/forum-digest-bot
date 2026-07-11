import random
from datetime import datetime, timezone
from db import Database, ThreadActivity
from snippets import FakeMessage
from digest import DigestRunner, DigestResult
from config import Config

class FakeGateway:
    def __init__(self, thread_messages=None, titles=None, starters=None):
        self.thread_messages = thread_messages or {}
        self.titles = titles or {}
        self.starters = starters or {}
        self.admin_notices = []
        self.sent_digests = []

    async def fetch_thread_messages(self, thread_id, since):
        return self.thread_messages.get(thread_id, [])

    async def get_thread_title_and_jump_url(self, thread_id):
        return self.titles.get(thread_id, (f"Thread {thread_id}", f"https://discord.com/x/{thread_id}"))

    async def get_starter_message(self, thread_id):
        return self.starters.get(thread_id, (False, "Starter excerpt"))

    async def send_admin_notice(self, guild_id, text):
        self.admin_notices.append(text)

    async def send_digest_messages(self, guild_id, messages):
        self.sent_digests.append(messages)

async def setup_db(tmp_path, guild_id=1, forum_id=10):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(forum_id, guild_id, now)
    await db.set_digest_channel(guild_id, 999)
    await db.set_digest_role(guild_id, 888)
    await db.set_admin_channel(guild_id, 777)
    return db, now

async def test_quiet_skip_notifies_admin_and_does_not_reset_window(tmp_path):
    db, now = await setup_db(tmp_path)
    await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=1)  # below threshold
    gateway = FakeGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    result = await runner.run(guild_id=1, manual=False)
    assert result.posted is False
    assert len(gateway.admin_notices) == 1
    assert gateway.sent_digests == []
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 1  # not cleared

async def test_digest_posts_eligible_thread_and_resets_window(tmp_path):
    db, now = await setup_db(tmp_path)
    for uid in [1, 2, 3]:
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
    gateway = FakeGateway(
        thread_messages={1: [FakeMessage(1, "great point", 1, 5, now, False)]},
    )
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    result = await runner.run(guild_id=1, manual=False)
    assert result.posted is True
    assert result.message_count == 1
    assert len(gateway.sent_digests) == 1
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 0  # window cleared after real digest
    assert activity.last_featured_at is not None
    cfg = await db.get_guild_config(1)
    assert cfg.last_digest_at is not None

async def test_digest_snippet_fetch_uses_window_start_not_now(tmp_path):
    db, now = await setup_db(tmp_path)
    last_digest = datetime(2026, 7, 7, tzinfo=timezone.utc)
    await db.set_last_digest_at(1, last_digest)
    for uid in [1, 2, 3]:
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)

    captured_since = []

    class WindowAwareGateway(FakeGateway):
        async def fetch_thread_messages(self, thread_id, since):
            captured_since.append(since)
            return [FakeMessage(1, "a great snippet", 1, 5, datetime(2026, 7, 8, tzinfo=timezone.utc), False)]

    gateway = WindowAwareGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    result = await runner.run(guild_id=1, manual=False)
    assert result.posted is True
    assert captured_since == [last_digest]  # window start, NOT "now"
    sent = gateway.sent_digests[0]
    assert any("a great snippet" in m.content for m in sent)

async def test_manual_digest_post_behaves_same_as_scheduled(tmp_path):
    db, now = await setup_db(tmp_path)
    for uid in [1, 2, 3]:
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
    gateway = FakeGateway(thread_messages={1: []})
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    result = await runner.run(guild_id=1, manual=True)
    assert result.posted is True

async def test_build_messages_renders_without_any_side_effects(tmp_path):
    db, now = await setup_db(tmp_path)
    for uid in [1, 2, 3]:
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
    gateway = FakeGateway(thread_messages={1: [FakeMessage(1, "great point", 1, 5, now, False)]})
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    selected, messages = await runner.build_messages(guild_id=1, now=now)
    assert [a.thread_id for a in selected] == [1]
    assert any("great point" in m.content for m in messages)
    assert any("**Thread 1**" in m.content for m in messages)
    # no posting, no notices, no state changes
    assert gateway.sent_digests == []
    assert gateway.admin_notices == []
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 6
    assert activity.last_featured_at is None
    assert (await db.get_guild_config(1)).last_digest_at is None

async def test_build_messages_empty_when_nothing_eligible_and_never_notifies(tmp_path):
    db, now = await setup_db(tmp_path)
    await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=1)  # below threshold
    gateway = FakeGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    selected, messages = await runner.build_messages(guild_id=1, now=now)
    assert selected == []
    assert messages == []
    assert gateway.admin_notices == []  # quiet-skip notice is run()'s job, not build's
