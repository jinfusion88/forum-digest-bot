import random
from datetime import datetime, timezone
from db import Database
from digest import DigestRunner
from cogs.digest_commands import DigestCog
from config import Config

class FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content, ephemeral=False, allowed_mentions=None):
        self.sent.append((content, ephemeral, allowed_mentions))

class FakeFollowup:
    def __init__(self):
        self.sent = []

    async def send(self, content, ephemeral=False, allowed_mentions=None):
        self.sent.append((content, ephemeral, allowed_mentions))

class FakeGuild:
    def __init__(self, id):
        self.id = id

class FakeInteraction:
    def __init__(self, guild_id):
        self.guild = FakeGuild(guild_id)
        self.response = FakeResponse()
        self.followup = FakeFollowup()

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

async def setup_eligible_thread(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    for uid in [1, 2, 3]:
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
    return db

async def test_preview_renders_full_digest_ephemerally_without_side_effects(tmp_path):
    db = await setup_eligible_thread(tmp_path)
    await db.set_digest_role(1, 888)
    gateway = FakeGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    cog = DigestCog(db, Config(), runner)
    interaction = FakeInteraction(guild_id=1)
    await cog.preview.callback(cog, interaction)

    # nothing posted publicly, nothing reset
    assert gateway.sent_digests == []
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 6
    assert activity.last_featured_at is None
    cfg = await db.get_guild_config(1)
    assert cfg.last_digest_at is None

    # the exact rendered digest, sent ephemerally
    content, ephemeral, allowed_mentions = interaction.response.sent[0]
    assert ephemeral is True
    assert "Here are the Featured Discussions This Week!" in content
    assert "**Thread 1**" in content
    assert "Go check out what's brewing → https://discord.com/x/1" in content
    assert "🔥 **6 replies** from **3 members** this week!" in content
    assert "<@&888>" in content  # ping text present in the rendering...

    # ...but disarmed: nothing may actually mention (AllowedMentions.none()
    # represents "suppress" as falsy flags, so assert falsiness, not [])
    assert allowed_mentions is not None
    assert not allowed_mentions.everyone
    assert not allowed_mentions.users
    assert not allowed_mentions.roles

async def test_preview_reports_when_nothing_is_eligible(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    gateway = FakeGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    cog = DigestCog(db, Config(), runner)
    interaction = FakeInteraction(guild_id=1)
    await cog.preview.callback(cog, interaction)
    content, ephemeral, _ = interaction.response.sent[0]
    assert "No threads are currently eligible." in content
    assert ephemeral is True
    assert gateway.admin_notices == []  # preview never notifies admins

async def test_stats_shows_eligible_threads_without_posting_or_resetting(tmp_path):
    db = await setup_eligible_thread(tmp_path)
    gateway = FakeGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    cog = DigestCog(db, Config(), runner)
    interaction = FakeInteraction(guild_id=1)
    await cog.stats.callback(cog, interaction)
    assert gateway.sent_digests == []
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 6  # untouched
    content, ephemeral, _ = interaction.response.sent[0]
    assert ephemeral is True
    assert "Thread 1" in content
    assert "6 messages" in content
    assert "3 participants" in content

async def test_post_command_triggers_manual_digest_and_resets_window(tmp_path):
    db = await setup_eligible_thread(tmp_path)
    gateway = FakeGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    cog = DigestCog(db, Config(), runner)
    interaction = FakeInteraction(guild_id=1)
    await cog.post.callback(cog, interaction)
    assert len(gateway.sent_digests) == 1
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 0
