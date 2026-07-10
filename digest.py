from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol

from config import Config
from db import Database
from scoring import select_featured
from snippets import FakeMessage, select_snippet
from digest_format import ThreadRenderData, format_digest


class DiscordGateway(Protocol):
    async def fetch_thread_messages(self, thread_id: int, since: datetime) -> list[FakeMessage]: ...
    async def get_thread_title_and_jump_url(self, thread_id: int) -> tuple[str, str]: ...
    async def get_starter_message(self, thread_id: int) -> tuple[bool, str]: ...
    async def send_admin_notice(self, guild_id: int, text: str) -> None: ...
    async def send_digest_messages(self, guild_id: int, messages) -> None: ...


@dataclass
class DigestResult:
    posted: bool
    message_count: int
    reason: str | None = None


class DigestRunner:
    def __init__(self, db: Database, config: Config, gateway: DiscordGateway, rng):
        self.db = db
        self.config = config
        self.gateway = gateway
        self.rng = rng

    async def run(self, guild_id: int, *, manual: bool) -> DigestResult:
        now = datetime.now(timezone.utc)
        candidates = await self.db.get_candidates(guild_id)
        selected = select_featured(
            candidates, now=now, cooldown_days=self.config.cooldown_days,
            min_messages=self.config.min_messages, min_participants=self.config.min_participants,
            max_featured=self.config.max_featured_threads, rng=self.rng,
        )

        if not selected:
            await self.gateway.send_admin_notice(
                guild_id, "No threads crossed the digest threshold this cycle."
            )
            return DigestResult(posted=False, message_count=0, reason="no_eligible_threads")

        guild_config = await self.db.get_guild_config(guild_id)   # move this fetch up
        window_start = guild_config.last_digest_at
        if window_start is None:
            forums = await self.db.get_monitored_forums(guild_id)
            window_start = min(
                (f.designated_at for f in forums),
                default=now - timedelta(days=7),
            )

        render_data = []
        for activity in selected:
            messages = await self.gateway.fetch_thread_messages(activity.thread_id, since=window_start)
            title, jump_url = await self.gateway.get_thread_title_and_jump_url(activity.thread_id)
            starter_is_url, starter_text = await self.gateway.get_starter_message(activity.thread_id)
            snippet = select_snippet(messages, char_budget=self.config.snippet_char_budget)
            render_data.append(ThreadRenderData(
                thread_id=activity.thread_id, title=title, jump_url=jump_url,
                starter_is_url=starter_is_url, starter_text=starter_text, snippet=snippet,
                reply_count=activity.message_count, participant_count=activity.unique_participant_count,
            ))

        if guild_config.digest_role_id is None:
            await self.gateway.send_admin_notice(
                guild_id, "No digest role configured - posting the digest without a role ping. Run /setup digest-role."
            )
        messages = format_digest(render_data, role_id=guild_config.digest_role_id, title=self.config.digest_title)
        await self.gateway.send_digest_messages(guild_id, messages)

        for activity in selected:
            await self.db.set_last_featured(activity.thread_id, now)
        await self.db.reset_guild_activity(guild_id)
        await self.db.set_last_digest_at(guild_id, now)

        return DigestResult(posted=True, message_count=len(selected))
