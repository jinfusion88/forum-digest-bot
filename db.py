from dataclasses import dataclass
from datetime import datetime, timezone
import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS guild_config (
  guild_id INTEGER PRIMARY KEY,
  digest_channel_id INTEGER,
  digest_role_id INTEGER,
  newthread_channel_id INTEGER,
  admin_channel_id INTEGER,
  last_digest_at TEXT
);
CREATE TABLE IF NOT EXISTS monitored_forums (
  forum_channel_id INTEGER PRIMARY KEY,
  guild_id INTEGER NOT NULL,
  designated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS thread_activity (
  thread_id INTEGER PRIMARY KEY,
  forum_channel_id INTEGER NOT NULL,
  created_at TEXT,
  message_count INTEGER NOT NULL DEFAULT 0,
  unique_participant_count INTEGER NOT NULL DEFAULT 0,
  reaction_count INTEGER NOT NULL DEFAULT 0,
  is_new_thread_boosted INTEGER NOT NULL DEFAULT 0,
  last_featured_at TEXT,
  counted_capped INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS thread_participants (
  thread_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  PRIMARY KEY (thread_id, user_id)
);
CREATE TABLE IF NOT EXISTS pending_newthread_announcements (
  thread_id INTEGER PRIMARY KEY,
  forum_channel_id INTEGER NOT NULL,
  guild_id INTEGER NOT NULL,
  due_at TEXT NOT NULL,
  posted INTEGER NOT NULL DEFAULT 0
);
"""


def _parse_dt(value):
    return datetime.fromisoformat(value) if value else None


def _fmt_dt(value):
    return value.isoformat() if value else None


@dataclass
class GuildConfig:
    guild_id: int
    digest_channel_id: int | None
    digest_role_id: int | None
    newthread_channel_id: int | None
    admin_channel_id: int | None
    last_digest_at: datetime | None


@dataclass
class MonitoredForum:
    forum_channel_id: int
    guild_id: int
    designated_at: datetime


@dataclass
class ThreadActivity:
    thread_id: int
    forum_channel_id: int
    created_at: datetime | None
    message_count: int
    unique_participant_count: int
    reaction_count: int
    is_new_thread_boosted: bool
    last_featured_at: datetime | None
    counted_capped: bool


@dataclass
class PendingAnnouncement:
    thread_id: int
    forum_channel_id: int
    guild_id: int
    due_at: datetime
    posted: bool


class Database:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection | None = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self):
        await self.conn.close()

    async def get_guild_config(self, guild_id: int) -> GuildConfig:
        cur = await self.conn.execute(
            "SELECT guild_id, digest_channel_id, digest_role_id, newthread_channel_id, "
            "admin_channel_id, last_digest_at FROM guild_config WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return GuildConfig(guild_id, None, None, None, None, None)
        return GuildConfig(row[0], row[1], row[2], row[3], row[4], _parse_dt(row[5]))

    async def _ensure_guild_row(self, guild_id: int):
        await self.conn.execute(
            "INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,)
        )

    async def set_digest_channel(self, guild_id: int, channel_id: int):
        await self._ensure_guild_row(guild_id)
        await self.conn.execute(
            "UPDATE guild_config SET digest_channel_id = ? WHERE guild_id = ?",
            (channel_id, guild_id),
        )
        await self.conn.commit()

    async def set_digest_role(self, guild_id: int, role_id: int):
        await self._ensure_guild_row(guild_id)
        await self.conn.execute(
            "UPDATE guild_config SET digest_role_id = ? WHERE guild_id = ?",
            (role_id, guild_id),
        )
        await self.conn.commit()

    async def set_newthread_channel(self, guild_id: int, channel_id: int):
        await self._ensure_guild_row(guild_id)
        await self.conn.execute(
            "UPDATE guild_config SET newthread_channel_id = ? WHERE guild_id = ?",
            (channel_id, guild_id),
        )
        await self.conn.commit()

    async def set_admin_channel(self, guild_id: int, channel_id: int):
        await self._ensure_guild_row(guild_id)
        await self.conn.execute(
            "UPDATE guild_config SET admin_channel_id = ? WHERE guild_id = ?",
            (channel_id, guild_id),
        )
        await self.conn.commit()

    async def set_last_digest_at(self, guild_id: int, when: datetime):
        await self._ensure_guild_row(guild_id)
        await self.conn.execute(
            "UPDATE guild_config SET last_digest_at = ? WHERE guild_id = ?",
            (_fmt_dt(when), guild_id),
        )
        await self.conn.commit()

    async def add_monitored_forum(self, forum_channel_id: int, guild_id: int, designated_at: datetime):
        await self.conn.execute(
            "INSERT OR REPLACE INTO monitored_forums (forum_channel_id, guild_id, designated_at) "
            "VALUES (?, ?, ?)",
            (forum_channel_id, guild_id, _fmt_dt(designated_at)),
        )
        await self.conn.commit()

    async def remove_monitored_forum(self, forum_channel_id: int):
        await self.conn.execute(
            "DELETE FROM monitored_forums WHERE forum_channel_id = ?", (forum_channel_id,)
        )
        await self.conn.commit()

    async def get_monitored_forums(self, guild_id: int) -> list[MonitoredForum]:
        cur = await self.conn.execute(
            "SELECT forum_channel_id, guild_id, designated_at FROM monitored_forums WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cur.fetchall()
        return [MonitoredForum(r[0], r[1], _parse_dt(r[2])) for r in rows]

    async def get_thread_activity(self, thread_id: int) -> ThreadActivity | None:
        cur = await self.conn.execute(
            "SELECT thread_id, forum_channel_id, created_at, message_count, "
            "unique_participant_count, reaction_count, is_new_thread_boosted, "
            "last_featured_at, counted_capped FROM thread_activity WHERE thread_id = ?",
            (thread_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return ThreadActivity(
            row[0], row[1], _parse_dt(row[2]), row[3], row[4], row[5],
            bool(row[6]), _parse_dt(row[7]), bool(row[8]),
        )

    async def upsert_thread_activity(self, activity: ThreadActivity):
        await self.conn.execute(
            "INSERT INTO thread_activity (thread_id, forum_channel_id, created_at, "
            "message_count, unique_participant_count, reaction_count, is_new_thread_boosted, "
            "last_featured_at, counted_capped) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(thread_id) DO UPDATE SET forum_channel_id=excluded.forum_channel_id, "
            "created_at=excluded.created_at, message_count=excluded.message_count, "
            "unique_participant_count=excluded.unique_participant_count, "
            "reaction_count=excluded.reaction_count, "
            "is_new_thread_boosted=excluded.is_new_thread_boosted, "
            "last_featured_at=excluded.last_featured_at, counted_capped=excluded.counted_capped",
            (
                activity.thread_id, activity.forum_channel_id, _fmt_dt(activity.created_at),
                activity.message_count, activity.unique_participant_count, activity.reaction_count,
                int(activity.is_new_thread_boosted), _fmt_dt(activity.last_featured_at),
                int(activity.counted_capped),
            ),
        )
        await self.conn.commit()

    async def add_participant(self, thread_id: int, user_id: int) -> bool:
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO thread_participants (thread_id, user_id) VALUES (?, ?)",
            (thread_id, user_id),
        )
        await self.conn.commit()
        return cur.rowcount > 0

    async def record_message(self, thread_id: int, forum_channel_id: int, created_at: datetime,
                              user_id: int, reaction_delta: int = 0):
        # add_participant's PRIMARY KEY constraint makes participant-uniqueness atomic;
        # the INSERT...ON CONFLICT below does the counter increment in one SQL statement
        # (not a Python read-modify-write), so two concurrent calls for the same thread
        # can never clobber each other's message_count/reaction_count increment.
        is_new_participant = await self.add_participant(thread_id, user_id)
        participant_increment = 1 if is_new_participant else 0
        await self.conn.execute(
            "INSERT INTO thread_activity (thread_id, forum_channel_id, created_at, "
            "message_count, unique_participant_count, reaction_count, is_new_thread_boosted, "
            "last_featured_at, counted_capped) VALUES (?, ?, ?, 1, ?, ?, 0, NULL, 0) "
            "ON CONFLICT(thread_id) DO UPDATE SET "
            "message_count = message_count + 1, "
            "reaction_count = reaction_count + excluded.reaction_count, "
            "unique_participant_count = unique_participant_count + ?",
            (thread_id, forum_channel_id, _fmt_dt(created_at), participant_increment,
             reaction_delta, participant_increment),
        )
        await self.conn.commit()

    async def reset_guild_activity(self, guild_id: int):
        forums = await self.get_monitored_forums(guild_id)
        forum_ids = [f.forum_channel_id for f in forums]
        if not forum_ids:
            return
        placeholders = ",".join("?" for _ in forum_ids)
        await self.conn.execute(
            f"UPDATE thread_activity SET message_count = 0, unique_participant_count = 0, "
            f"reaction_count = 0, counted_capped = 0 WHERE forum_channel_id IN ({placeholders})",
            forum_ids,
        )
        cur = await self.conn.execute(
            f"SELECT thread_id FROM thread_activity WHERE forum_channel_id IN ({placeholders})",
            forum_ids,
        )
        thread_ids = [r[0] for r in await cur.fetchall()]
        if thread_ids:
            tp = ",".join("?" for _ in thread_ids)
            await self.conn.execute(
                f"DELETE FROM thread_participants WHERE thread_id IN ({tp})", thread_ids
            )
        await self.conn.commit()

    async def set_last_featured(self, thread_id: int, when: datetime):
        await self.conn.execute(
            "UPDATE thread_activity SET last_featured_at = ? WHERE thread_id = ?",
            (_fmt_dt(when), thread_id),
        )
        await self.conn.commit()

    async def get_candidates(self, guild_id: int) -> list[ThreadActivity]:
        forums = await self.get_monitored_forums(guild_id)
        forum_ids = [f.forum_channel_id for f in forums]
        if not forum_ids:
            return []
        placeholders = ",".join("?" for _ in forum_ids)
        cur = await self.conn.execute(
            f"SELECT thread_id, forum_channel_id, created_at, message_count, "
            f"unique_participant_count, reaction_count, is_new_thread_boosted, "
            f"last_featured_at, counted_capped FROM thread_activity "
            f"WHERE forum_channel_id IN ({placeholders})",
            forum_ids,
        )
        rows = await cur.fetchall()
        return [
            ThreadActivity(
                r[0], r[1], _parse_dt(r[2]), r[3], r[4], r[5], bool(r[6]), _parse_dt(r[7]), bool(r[8])
            )
            for r in rows
        ]

    async def add_pending_announcement(self, a: PendingAnnouncement):
        await self.conn.execute(
            "INSERT OR REPLACE INTO pending_newthread_announcements "
            "(thread_id, forum_channel_id, guild_id, due_at, posted) VALUES (?,?,?,?,?)",
            (a.thread_id, a.forum_channel_id, a.guild_id, _fmt_dt(a.due_at), int(a.posted)),
        )
        await self.conn.commit()

    async def get_unposted_announcements(self, guild_id: int) -> list[PendingAnnouncement]:
        cur = await self.conn.execute(
            "SELECT thread_id, forum_channel_id, guild_id, due_at, posted "
            "FROM pending_newthread_announcements WHERE posted = 0 AND guild_id = ?",
            (guild_id,),
        )
        rows = await cur.fetchall()
        return [PendingAnnouncement(r[0], r[1], r[2], _parse_dt(r[3]), bool(r[4])) for r in rows]

    async def mark_announcement_posted(self, thread_id: int):
        await self.conn.execute(
            "UPDATE pending_newthread_announcements SET posted = 1 WHERE thread_id = ?",
            (thread_id,),
        )
        await self.conn.commit()
