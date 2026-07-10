import random
from datetime import datetime, timezone
from db import Database
from digest import DigestRunner
from cogs.digest_commands import DigestCog
from config import Config

class FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content, ephemeral=False):
        self.sent.append((content, ephemeral))

class FakeGuild:
    def __init__(self, id):
        self.id = id

class FakeInteraction:
    def __init__(self, guild_id):
        self.guild = FakeGuild(guild_id)
        self.response = FakeResponse()

class FakeGateway:
    def __init__(self):
        self.admin_notices = []
        self.sent_digests = []

    async def fetch_thread_messages(self, thread_id, since):
        return []

    async def get_thread_title_and_jump_url(self, thread_id):
        return f"Thread {thread_id}", f"https://discord.com/x/{thread_id}"

    async def get_starter_message(self, thread_id):
        return False, "excerpt"

    async def send_admin_notice(self, guild_id, text):
        self.admin_notices.append(text)

    async def send_digest_messages(self, guild_id, messages):
        self.sent_digests.append(messages)

async def test_preview_shows_eligible_threads_without_posting_or_resetting(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    for uid in [1, 2, 3]:
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
    gateway = FakeGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    cog = DigestCog(db, Config(), runner)
    interaction = FakeInteraction(guild_id=1)
    await cog.preview.callback(cog, interaction)
    assert gateway.sent_digests == []
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 6  # untouched
    assert interaction.response.sent[0][1] is True  # ephemeral
    assert "Thread 1" in interaction.response.sent[0][0]

async def test_post_command_triggers_manual_digest_and_resets_window(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    for uid in [1, 2, 3]:
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
    gateway = FakeGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    cog = DigestCog(db, Config(), runner)
    interaction = FakeInteraction(guild_id=1)
    await cog.post.callback(cog, interaction)
    assert len(gateway.sent_digests) == 1
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 0
