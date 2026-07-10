import re
from datetime import datetime

import discord

from snippets import FakeMessage
from backfill import BackfillMessage, DiscoveredThread
from digest_format import DigestMessage

_URL_RE = re.compile(r"^https?://\S+$")


class RealDiscordGateway:
    def __init__(self, client: discord.Client, db):
        self.client = client
        self.db = db

    @staticmethod
    def _is_bare_url(text: str) -> bool:
        return bool(_URL_RE.match(text.strip()))

    @staticmethod
    def _to_fake_message(message) -> FakeMessage:
        reaction_count = sum(r.count for r in message.reactions)
        is_attachment_only = not message.content.strip() and (
            bool(message.attachments) or bool(message.embeds)
        )
        return FakeMessage(
            id=message.id, content=message.content, author_id=message.author.id,
            reaction_count=reaction_count, created_at=message.created_at,
            is_attachment_or_embed_only=is_attachment_only,
        )

    @staticmethod
    def _to_backfill_message(message) -> BackfillMessage:
        reaction_count = sum(r.count for r in message.reactions)
        return BackfillMessage(author_id=message.author.id, reaction_count=reaction_count)

    # --- DiscordGateway protocol (digest.py) ---

    async def fetch_thread_messages(self, thread_id: int, since: datetime) -> list[FakeMessage]:
        thread = self.client.get_channel(thread_id) or await self.client.fetch_channel(thread_id)
        return [self._to_fake_message(m) async for m in thread.history(after=since, limit=None)]

    async def get_thread_title_and_jump_url(self, thread_id: int) -> tuple[str, str]:
        thread = self.client.get_channel(thread_id) or await self.client.fetch_channel(thread_id)
        return thread.name, thread.jump_url

    async def get_starter_message(self, thread_id: int) -> tuple[bool, str]:
        thread = self.client.get_channel(thread_id) or await self.client.fetch_channel(thread_id)
        starter = await thread.fetch_message(thread.id)
        if self._is_bare_url(starter.content):
            return True, starter.content.strip()
        return False, starter.content[:280]

    async def send_admin_notice(self, guild_id: int, text: str) -> None:
        guild_config = await self.db.get_guild_config(guild_id)
        if guild_config.admin_channel_id is None:
            return
        channel = self.client.get_channel(guild_config.admin_channel_id)
        if channel is not None:
            await channel.send(text, allowed_mentions=discord.AllowedMentions.none())

    async def send_digest_messages(self, guild_id: int, messages: list[DigestMessage]) -> None:
        guild_config = await self.db.get_guild_config(guild_id)
        channel = self.client.get_channel(guild_config.digest_channel_id)
        for m in messages:
            await channel.send(
                m.content,
                allowed_mentions=discord.AllowedMentions(roles=[discord.Object(r) for r in m.mention_role_ids]),
            )

    # --- BackfillGateway protocol (backfill.py) ---

    async def list_active_and_recent_archived_threads(self, forum_channel_id: int) -> list[DiscoveredThread]:
        forum = self.client.get_channel(forum_channel_id) or await self.client.fetch_channel(forum_channel_id)
        discovered = [DiscoveredThread(t.id, t.created_at) for t in forum.threads]
        async for t in forum.archived_threads(limit=100):
            discovered.append(DiscoveredThread(t.id, t.created_at))
        return discovered

    async def fetch_messages_since(self, thread_id: int, since: datetime, cap: int) -> list[BackfillMessage]:
        thread = self.client.get_channel(thread_id) or await self.client.fetch_channel(thread_id)
        results = []
        async for m in thread.history(after=since, limit=cap, oldest_first=False):
            results.append(self._to_backfill_message(m))
        return results

    # --- NewThreadGateway protocol (newthread.py) ---

    async def thread_exists_and_accessible(self, thread_id: int) -> bool:
        try:
            thread = self.client.get_channel(thread_id) or await self.client.fetch_channel(thread_id)
            return thread is not None
        except discord.NotFound:
            return False
        except discord.Forbidden:
            return False

    async def post_new_thread_announcement(self, forum_channel_id: int, thread_id: int) -> None:
        thread = self.client.get_channel(thread_id) or await self.client.fetch_channel(thread_id)
        guild_id = thread.guild.id
        guild_config = await self.db.get_guild_config(guild_id)
        channel = self.client.get_channel(guild_config.newthread_channel_id)
        await channel.send(
            f"New thread: **{thread.name}**\n<{thread.jump_url}>",
            allowed_mentions=discord.AllowedMentions.none(),
        )
