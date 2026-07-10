from datetime import datetime, timezone
from db import Database
from cogs.setup_commands import SetupCog

class FakeChannel:
    def __init__(self, id, name="general"):
        self.id = id
        self.name = name

class FakeRole:
    def __init__(self, id, name="mtg talk"):
        self.id = id
        self.name = name

class FakeGuild:
    def __init__(self, id):
        self.id = id

class FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content, ephemeral=False):
        self.sent.append((content, ephemeral))

class FakeInteraction:
    def __init__(self, guild_id):
        self.guild = FakeGuild(guild_id)
        self.response = FakeResponse()

async def test_setup_digest_channel_persists_to_db(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    cog = SetupCog(db)
    interaction = FakeInteraction(guild_id=1)
    channel = FakeChannel(id=555)
    await cog.digest_channel.callback(cog, interaction, channel)
    cfg = await db.get_guild_config(1)
    assert cfg.digest_channel_id == 555
    assert interaction.response.sent[0][1] is True  # ephemeral

async def test_setup_add_forum_persists_designation_timestamp(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    cog = SetupCog(db)
    interaction = FakeInteraction(guild_id=1)
    forum = FakeChannel(id=10, name="Scion")
    await cog.add_forum.callback(cog, interaction, forum)
    forums = await db.get_monitored_forums(1)
    assert len(forums) == 1
    assert forums[0].forum_channel_id == 10

async def test_setup_remove_forum(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    cog = SetupCog(db)
    interaction = FakeInteraction(guild_id=1)
    forum = FakeChannel(id=10, name="Scion")
    await cog.remove_forum.callback(cog, interaction, forum)
    assert await db.get_monitored_forums(1) == []

async def test_setup_show_reports_current_configuration(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    await db.set_digest_channel(1, 555)
    await db.set_digest_role(1, 777)
    cog = SetupCog(db)
    interaction = FakeInteraction(guild_id=1)
    await cog.show.callback(cog, interaction)
    content = interaction.response.sent[0][0]
    assert "555" in content
    assert "777" in content
