from datetime import datetime, timezone

from discord.ext import commands

from db import Database
from newthread import NewThreadAnnouncer
from config import Config


class ForumTrackingCog(commands.Cog):
    def __init__(self, db: Database, announcer: NewThreadAnnouncer, config: Config):
        self.db = db
        self.announcer = announcer
        self.config = config

    async def _is_monitored(self, forum_channel_id: int, guild_id: int) -> bool:
        forums = await self.db.get_monitored_forums(guild_id)
        return any(f.forum_channel_id == forum_channel_id for f in forums)

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        if not await self._is_monitored(thread.parent_id, thread.guild.id):
            return
        now = datetime.now(timezone.utc)
        await self.announcer.register_new_thread(
            thread_id=thread.id, forum_channel_id=thread.parent_id, guild_id=thread.guild.id,
            now=now, delay_minutes=self.config.new_thread_delay_minutes,
        )

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        thread = message.channel
        parent_id = getattr(thread, "parent_id", None)
        if parent_id is None:
            return
        if not await self._is_monitored(parent_id, thread.guild.id):
            return
        await self.db.record_message(
            thread_id=thread.id, forum_channel_id=parent_id,
            created_at=datetime.now(timezone.utc), user_id=message.author.id,
        )
