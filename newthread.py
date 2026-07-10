from datetime import datetime, timedelta
from typing import Protocol

from db import Database, PendingAnnouncement


def is_stale(due_at: datetime, now: datetime, staleness_cap_hours: int) -> bool:
    return now - due_at > timedelta(hours=staleness_cap_hours)


class NewThreadGateway(Protocol):
    async def thread_exists_and_accessible(self, thread_id: int) -> bool: ...
    async def post_new_thread_announcement(self, forum_channel_id: int, thread_id: int) -> None: ...
    async def send_admin_notice(self, guild_id: int, text: str) -> None: ...


class NewThreadAnnouncer:
    def __init__(self, db: Database, gateway: NewThreadGateway):
        self.db = db
        self.gateway = gateway

    async def register_new_thread(
        self, thread_id: int, forum_channel_id: int, guild_id: int, now: datetime, delay_minutes: int
    ) -> None:
        due_at = now + timedelta(minutes=delay_minutes)
        await self.db.add_pending_announcement(
            PendingAnnouncement(
                thread_id=thread_id, forum_channel_id=forum_channel_id, guild_id=guild_id,
                due_at=due_at, posted=False,
            )
        )

    async def process_due_announcements(self, guild_id: int, now: datetime, staleness_cap_hours: int) -> None:
        pending = await self.db.get_unposted_announcements(guild_id)
        for row in pending:
            if row.due_at > now:
                continue
            if is_stale(row.due_at, now, staleness_cap_hours):
                await self.gateway.send_admin_notice(
                    guild_id,
                    f"Skipped a new-thread announcement for thread {row.thread_id} "
                    f"(more than {staleness_cap_hours}h overdue, likely due to downtime).",
                )
                await self.db.mark_announcement_posted(row.thread_id)
                continue
            if not await self.gateway.thread_exists_and_accessible(row.thread_id):
                await self.db.mark_announcement_posted(row.thread_id)
                continue
            await self.gateway.post_new_thread_announcement(row.forum_channel_id, row.thread_id)
            await self.db.mark_announcement_posted(row.thread_id)
