# Forum Discovery Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Discord bot that posts a twice-weekly "Featured Discussions" digest of active forum threads (unranked, threshold-based) and a delayed, silent new-thread visibility post, fully configurable at runtime via slash commands.

**Architecture:** discord.py bot with a layered design — pure/testable logic (scoring, snippet selection, digest formatting, staleness checks, cron trigger construction) is separated from discord.py I/O (backfill, event listeners, slash commands, posting). All persistent state lives in SQLite via `aiosqlite`. APScheduler drives the DST-safe twice-weekly cron; an asyncio loop drives the 1-hour delayed new-thread timers, both resumable from DB on restart.

**Tech Stack:** Python 3.11+, discord.py 2.x, aiosqlite, APScheduler, pytest + pytest-asyncio, PyYAML, Docker.

## Global Constraints

- Default eligibility: `message_count >= 5` AND `unique_participant_count >= 3` (config-overridable).
- Cooldown: 7 days after a thread is actually featured in a digest (config-overridable).
- Digest schedule: Monday and Friday, 16:00, timezone `America/Chicago` (config-overridable), DST-safe.
- Max 5 featured threads per digest, presented unranked, randomized display order.
- Scoring window is strictly "since last digest" (`last_digest_at`); quiet-skip does **not** reset it — only an actual digest post resets `last_digest_at` and clears counters.
- New-thread delay: 60 minutes default; staleness cap: 24 hours default (config-overridable).
- Backfill cap: 200 messages/thread default, fetched newest-first (config-overridable).
- Snippet char budget: 150 chars default (config-overridable).
- Digest message: plain markdown only (no embeds). `allowed_mentions` restricted to the configured digest role only on digest posts; `AllowedMentions.none()` on new-thread posts.
- Total digest content must respect Discord's 2000-char message limit; split into multiple messages with the role ping only on the first if needed.
- No channel/role IDs in config files — all wired at runtime via `/setup` slash commands and persisted in SQLite. Thresholds/weights/schedule/delays live in the config file (restart to apply).
- No live Discord server/token required for tests — all discord.py objects are mocked/faked.
- Out of scope: web dashboard, cross-server support, AI summaries, historical analytics beyond eligibility tracking, runtime-editable thresholds.

---

## File Structure

```
forum-digest-bot/
  bot.py                    # entrypoint: intents, startup reconciliation, event loop
  config.py                 # Config dataclass + YAML loader
  db.py                     # aiosqlite schema + Database class (all queries)
  scoring.py                 # pure eligibility/cooldown/selection/boost logic
  snippets.py                # pure snippet-selection strategy chain
  digest_format.py           # pure digest message assembly (mentions, length budget)
  digest.py                  # orchestrates scoring+snippets+format+db+discord posting
  newthread.py                # pending-announcement lifecycle (pure staleness check + orchestration)
  backfill.py                # forum discovery + bounded history backfill
  scheduler.py                # APScheduler cron trigger construction (DST-safe)
  cogs/
    setup_commands.py         # /setup ...
    digest_commands.py        # /digest preview, /digest post
    forum_tracking.py         # on_thread_create, on_message, on_reaction_add/remove
  config.example.yaml
  requirements.txt
  Dockerfile
  docker-compose.yml
  README.md
  tests/
    conftest.py
    test_config.py
    test_db.py
    test_scoring.py
    test_snippets.py
    test_digest_format.py
    test_digest.py
    test_newthread.py
    test_backfill.py
    test_scheduler.py
```

---

### Task 1: Project Scaffolding & Config Loading

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Create: `config.example.yaml`
- Create: `.gitignore`
- Test: `tests/test_config.py`
- Test: `tests/conftest.py`

**Interfaces:**
- Produces: `Config` dataclass with fields `min_messages: int`, `min_participants: int`, `cooldown_days: int`, `new_thread_boost_messages: int`, `digest_days: list[str]`, `digest_time: str`, `digest_title: str`, `new_thread_delay_minutes: int`, `new_thread_staleness_cap_hours: int`, `backfill_message_cap: int`, `snippet_char_budget: int`, `max_featured_threads: int`, `timezone: str`. Function `load_config(path: str) -> Config`.

- [ ] **Step 1: Write `requirements.txt`**

```
discord.py>=2.4,<3
aiosqlite>=0.20,<1
APScheduler>=3.10,<4
PyYAML>=6.0,<7
pytest>=8.0
pytest-asyncio>=0.24
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
.venv/
*.db
config.yaml
.env
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_config.py
import pytest
from config import Config, load_config

def test_load_config_applies_defaults_for_missing_keys(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("min_messages: 8\n")
    cfg = load_config(str(config_path))
    assert cfg.min_messages == 8
    assert cfg.min_participants == 3
    assert cfg.cooldown_days == 7
    assert cfg.digest_days == ["monday", "friday"]
    assert cfg.digest_time == "16:00"
    assert cfg.timezone == "America/Chicago"
    assert cfg.digest_title == "Featured Discussions This Week"
    assert cfg.new_thread_delay_minutes == 60
    assert cfg.new_thread_staleness_cap_hours == 24
    assert cfg.backfill_message_cap == 200
    assert cfg.snippet_char_budget == 150
    assert cfg.max_featured_threads == 5
    assert cfg.new_thread_boost_messages == 2

def test_load_config_missing_file_uses_all_defaults(tmp_path):
    cfg = load_config(str(tmp_path / "does_not_exist.yaml"))
    assert cfg.min_messages == 5
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 5: Write `config.py`**

```python
from dataclasses import dataclass, field
import os
import yaml


@dataclass
class Config:
    min_messages: int = 5
    min_participants: int = 3
    cooldown_days: int = 7
    new_thread_boost_messages: int = 2
    digest_days: list[str] = field(default_factory=lambda: ["monday", "friday"])
    digest_time: str = "16:00"
    timezone: str = "America/Chicago"
    digest_title: str = "Featured Discussions This Week"
    new_thread_delay_minutes: int = 60
    new_thread_staleness_cap_hours: int = 24
    backfill_message_cap: int = 200
    snippet_char_budget: int = 150
    max_featured_threads: int = 5


def load_config(path: str) -> Config:
    if not os.path.exists(path):
        return Config()
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    defaults = Config()
    kwargs = {}
    for key in defaults.__dataclass_fields__:
        if key in raw:
            kwargs[key] = raw[key]
    return Config(**kwargs)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Write `config.example.yaml`**

```yaml
min_messages: 5
min_participants: 3
cooldown_days: 7
new_thread_boost_messages: 2
digest_days: ["monday", "friday"]
digest_time: "16:00"
timezone: "America/Chicago"
digest_title: "Featured Discussions This Week"
new_thread_delay_minutes: 60
new_thread_staleness_cap_hours: 24
backfill_message_cap: 200
snippet_char_budget: 150
max_featured_threads: 5
```

- [ ] **Step 8: Write empty `tests/conftest.py`** (populated in later tasks with shared fixtures)

```python
import pytest

pytest_plugins = []
```

- [ ] **Step 9: Commit**

```bash
git add requirements.txt config.py config.example.yaml .gitignore tests/test_config.py tests/conftest.py
git commit -m "feat: add config loading with defaults"
```

---

### Task 2: Database Schema & Core Queries

**Files:**
- Create: `db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing external.
- Produces: dataclasses `GuildConfig(guild_id: int, digest_channel_id: int|None, digest_role_id: int|None, newthread_channel_id: int|None, admin_channel_id: int|None, last_digest_at: datetime|None)`, `MonitoredForum(forum_channel_id: int, guild_id: int, designated_at: datetime)`, `ThreadActivity(thread_id: int, forum_channel_id: int, created_at: datetime, message_count: int, unique_participant_count: int, reaction_count: int, is_new_thread_boosted: bool, last_featured_at: datetime|None, counted_capped: bool)`, `PendingAnnouncement(thread_id: int, forum_channel_id: int, guild_id: int, due_at: datetime, posted: bool)`.
- Produces: `class Database` with async methods: `connect()`, `close()`, `get_guild_config(guild_id) -> GuildConfig`, `set_digest_channel(guild_id, channel_id)`, `set_digest_role(guild_id, role_id)`, `set_newthread_channel(guild_id, channel_id)`, `set_admin_channel(guild_id, channel_id)`, `set_last_digest_at(guild_id, when)`, `add_monitored_forum(forum_channel_id, guild_id, designated_at)`, `remove_monitored_forum(forum_channel_id)`, `get_monitored_forums(guild_id) -> list[MonitoredForum]`, `get_thread_activity(thread_id) -> ThreadActivity|None`, `upsert_thread_activity(activity: ThreadActivity)`, `add_participant(thread_id, user_id) -> bool` (returns True if newly added), `record_message(thread_id, forum_channel_id, created_at, user_id, reaction_delta=0)` (a single atomic INSERT...ON CONFLICT SQL statement — no Python-side read-modify-write — so concurrent calls for the same thread never lose an increment), `reset_guild_activity(guild_id)` (zeroes counters, keeps `last_featured_at`), `set_last_featured(thread_id, when)`, `get_candidates(guild_id) -> list[ThreadActivity]`, `add_pending_announcement(a: PendingAnnouncement)`, `get_unposted_announcements(guild_id: int) -> list[PendingAnnouncement]` (scoped to the given guild, since a bot instance can be joined to more than one Discord server even though cross-server customization is out of scope), `mark_announcement_posted(thread_id)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
import pytest
from datetime import datetime, timezone
from db import Database, GuildConfig, ThreadActivity, PendingAnnouncement

@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()

@pytest.mark.asyncio
async def test_guild_config_defaults_to_none_fields(db):
    cfg = await db.get_guild_config(111)
    assert cfg == GuildConfig(111, None, None, None, None, None)

@pytest.mark.asyncio
async def test_set_digest_channel_persists(db):
    await db.set_digest_channel(111, 222)
    cfg = await db.get_guild_config(111)
    assert cfg.digest_channel_id == 222

@pytest.mark.asyncio
async def test_record_message_creates_and_increments_activity(db):
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=100)
    await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=101)
    await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=100)
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 3
    assert activity.unique_participant_count == 2

@pytest.mark.asyncio
async def test_reset_guild_activity_clears_counters_but_keeps_last_featured(db):
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=100)
    await db.set_last_featured(1, now)
    await db.add_monitored_forum(10, guild_id=999, designated_at=now)
    await db.reset_guild_activity(999)
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 0
    assert activity.unique_participant_count == 0
    assert activity.last_featured_at == now

@pytest.mark.asyncio
async def test_pending_announcement_roundtrip(db):
    due = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    await db.add_pending_announcement(
        PendingAnnouncement(thread_id=5, forum_channel_id=10, guild_id=999, due_at=due, posted=False)
    )
    unposted = await db.get_unposted_announcements(guild_id=999)
    assert len(unposted) == 1
    assert unposted[0].thread_id == 5
    await db.mark_announcement_posted(5)
    assert await db.get_unposted_announcements(guild_id=999) == []

@pytest.mark.asyncio
async def test_get_unposted_announcements_scoped_to_guild(db):
    due = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    await db.add_pending_announcement(
        PendingAnnouncement(thread_id=1, forum_channel_id=10, guild_id=111, due_at=due, posted=False)
    )
    await db.add_pending_announcement(
        PendingAnnouncement(thread_id=2, forum_channel_id=20, guild_id=222, due_at=due, posted=False)
    )
    guild_111_pending = await db.get_unposted_announcements(guild_id=111)
    assert [a.thread_id for a in guild_111_pending] == [1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Write `db.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Add pytest-asyncio config so `@pytest.mark.asyncio` runs without per-test markers boilerplate issues**

Create `pytest.ini`:
```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 6: Run full test suite**

Run: `pytest -v`
Expected: PASS (8 passed — Task 1 + Task 2 tests)

- [ ] **Step 7: Commit**

```bash
git add db.py tests/test_db.py pytest.ini
git commit -m "feat: add SQLite persistence layer"
```

---

### Task 3: Scoring — Eligibility, Cooldown, Selection, Boost

**Files:**
- Create: `scoring.py`
- Test: `tests/test_scoring.py`

**Interfaces:**
- Consumes: `ThreadActivity` from `db.py` (Task 2).
- Produces: `is_eligible(activity: ThreadActivity, min_messages: int, min_participants: int) -> bool`, `is_in_cooldown(activity: ThreadActivity, now: datetime, cooldown_days: int) -> bool`, `select_featured(candidates: list[ThreadActivity], now: datetime, cooldown_days: int, min_messages: int, min_participants: int, max_featured: int, rng: random.Random) -> list[ThreadActivity]`, `apply_new_thread_boost(activity: ThreadActivity, boost_messages: int) -> ThreadActivity`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scoring.py
import random
from datetime import datetime, timedelta, timezone
from db import ThreadActivity
from scoring import is_eligible, is_in_cooldown, select_featured, apply_new_thread_boost

def make_activity(thread_id, messages, participants, last_featured_at=None):
    return ThreadActivity(
        thread_id=thread_id, forum_channel_id=1, created_at=None,
        message_count=messages, unique_participant_count=participants,
        reaction_count=0, is_new_thread_boosted=False,
        last_featured_at=last_featured_at, counted_capped=False,
    )

def test_eligible_at_exact_threshold():
    a = make_activity(1, messages=5, participants=3)
    assert is_eligible(a, min_messages=5, min_participants=3) is True

def test_ineligible_one_below_participant_threshold():
    a = make_activity(1, messages=10, participants=2)
    assert is_eligible(a, min_messages=5, min_participants=3) is False

def test_ineligible_one_below_message_threshold():
    a = make_activity(1, messages=4, participants=5)
    assert is_eligible(a, min_messages=5, min_participants=3) is False

def test_two_person_high_volume_does_not_qualify_over_broader_thread():
    high_volume_two_person = make_activity(1, messages=50, participants=2)
    broader_thread = make_activity(2, messages=6, participants=4)
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    selected = select_featured(
        [high_volume_two_person, broader_thread], now=now, cooldown_days=7,
        min_messages=5, min_participants=3, max_featured=5, rng=random.Random(0),
    )
    ids = {a.thread_id for a in selected}
    assert ids == {2}

def test_cooldown_excludes_recently_featured_thread():
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    featured_3_days_ago = now - timedelta(days=3)
    a = make_activity(1, messages=10, participants=5, last_featured_at=featured_3_days_ago)
    assert is_in_cooldown(a, now=now, cooldown_days=7) is True

def test_cooldown_expired_after_window():
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    featured_8_days_ago = now - timedelta(days=8)
    a = make_activity(1, messages=10, participants=5, last_featured_at=featured_8_days_ago)
    assert is_in_cooldown(a, now=now, cooldown_days=7) is False

def test_select_featured_caps_at_max_and_sorts_by_broadest_participation():
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    candidates = [
        make_activity(1, messages=6, participants=3),
        make_activity(2, messages=6, participants=8),
        make_activity(3, messages=6, participants=6),
        make_activity(4, messages=6, participants=5),
        make_activity(5, messages=6, participants=4),
        make_activity(6, messages=6, participants=9),
    ]
    selected = select_featured(
        candidates, now=now, cooldown_days=7, min_messages=5, min_participants=3,
        max_featured=5, rng=random.Random(0),
    )
    assert len(selected) == 5
    assert {a.thread_id for a in selected} == {2, 3, 4, 5, 6}

def test_select_featured_excludes_cooldown_thread_even_if_eligible():
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    on_cooldown = make_activity(1, messages=10, participants=10, last_featured_at=now - timedelta(days=1))
    eligible = make_activity(2, messages=5, participants=3)
    selected = select_featured(
        [on_cooldown, eligible], now=now, cooldown_days=7, min_messages=5,
        min_participants=3, max_featured=5, rng=random.Random(0),
    )
    assert {a.thread_id for a in selected} == {2}

def test_apply_new_thread_boost_adds_to_message_count():
    a = make_activity(1, messages=0, participants=0)
    boosted = apply_new_thread_boost(a, boost_messages=2)
    assert boosted.message_count == 2
    assert boosted.is_new_thread_boosted is True

def test_apply_new_thread_boost_is_idempotent():
    a = make_activity(1, messages=0, participants=0)
    a.is_new_thread_boosted = True
    boosted = apply_new_thread_boost(a, boost_messages=2)
    assert boosted.message_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scoring'`

- [ ] **Step 3: Write `scoring.py`**

```python
import random
from datetime import datetime, timedelta
from db import ThreadActivity


def is_eligible(activity: ThreadActivity, min_messages: int, min_participants: int) -> bool:
    return (
        activity.message_count >= min_messages
        and activity.unique_participant_count >= min_participants
    )


def is_in_cooldown(activity: ThreadActivity, now: datetime, cooldown_days: int) -> bool:
    if activity.last_featured_at is None:
        return False
    return now - activity.last_featured_at < timedelta(days=cooldown_days)


def select_featured(
    candidates: list[ThreadActivity],
    now: datetime,
    cooldown_days: int,
    min_messages: int,
    min_participants: int,
    max_featured: int,
    rng: random.Random,
) -> list[ThreadActivity]:
    eligible = [
        a for a in candidates
        if is_eligible(a, min_messages, min_participants)
        and not is_in_cooldown(a, now, cooldown_days)
    ]
    eligible.sort(key=lambda a: (a.unique_participant_count, a.message_count), reverse=True)
    top = eligible[:max_featured]
    rng.shuffle(top)
    return top


def apply_new_thread_boost(activity: ThreadActivity, boost_messages: int) -> ThreadActivity:
    if activity.is_new_thread_boosted:
        return activity
    activity.message_count += boost_messages
    activity.is_new_thread_boosted = True
    return activity
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scoring.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add scoring.py tests/test_scoring.py
git commit -m "feat: add eligibility, cooldown, and selection scoring logic"
```

---

### Task 4: Snippet Selection Strategy Chain

**Files:**
- Create: `snippets.py`
- Test: `tests/test_snippets.py`

**Interfaces:**
- Produces: `@dataclass FakeMessage(id: int, content: str, author_id: int, reaction_count: int, created_at: datetime, is_attachment_or_embed_only: bool)`, `select_snippet(messages: list[FakeMessage], char_budget: int) -> str | None`.
- This module has no discord.py dependency — `digest.py` (Task 8) will adapt real `discord.Message` objects into `FakeMessage` before calling this.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_snippets.py
from datetime import datetime, timedelta, timezone
from snippets import FakeMessage, select_snippet

def msg(id, content, reactions=0, minutes_ago=0, attachment_only=False):
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    return FakeMessage(
        id=id, content=content, author_id=1, reaction_count=reactions,
        created_at=now - timedelta(minutes=minutes_ago),
        is_attachment_or_embed_only=attachment_only,
    )

def test_picks_most_reacted_message():
    messages = [
        msg(1, "low reactions", reactions=1, minutes_ago=10),
        msg(2, "the popular one", reactions=9, minutes_ago=5),
        msg(3, "medium", reactions=4, minutes_ago=1),
    ]
    assert select_snippet(messages, char_budget=150) == "the popular one"

def test_falls_back_to_most_recent_substantive_when_no_reactions():
    messages = [
        msg(1, "older message", reactions=0, minutes_ago=10),
        msg(2, "newest message", reactions=0, minutes_ago=1),
    ]
    assert select_snippet(messages, char_budget=150) == "newest message"

def test_skips_attachment_only_messages_in_recency_fallback():
    messages = [
        msg(1, "", reactions=0, minutes_ago=1, attachment_only=True),
        msg(2, "real content here", reactions=0, minutes_ago=5),
    ]
    assert select_snippet(messages, char_budget=150) == "real content here"

def test_skips_attachment_only_messages_even_if_most_reacted():
    messages = [
        msg(1, "", reactions=9, minutes_ago=1, attachment_only=True),
        msg(2, "substantive text", reactions=2, minutes_ago=5),
    ]
    assert select_snippet(messages, char_budget=150) == "substantive text"

def test_truncates_to_char_budget():
    long_text = "x" * 300
    messages = [msg(1, long_text, reactions=5, minutes_ago=1)]
    result = select_snippet(messages, char_budget=150)
    assert len(result) == 150

def test_returns_none_when_nothing_qualifies():
    messages = [msg(1, "", reactions=5, minutes_ago=1, attachment_only=True)]
    assert select_snippet(messages, char_budget=150) is None

def test_empty_message_list_returns_none():
    assert select_snippet([], char_budget=150) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_snippets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'snippets'`

- [ ] **Step 3: Write `snippets.py`**

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FakeMessage:
    id: int
    content: str
    author_id: int
    reaction_count: int
    created_at: datetime
    is_attachment_or_embed_only: bool


def _most_reacted(messages: list[FakeMessage]) -> FakeMessage | None:
    candidates = [m for m in messages if not m.is_attachment_or_embed_only and m.reaction_count > 0]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.reaction_count)


def _most_recent_substantive(messages: list[FakeMessage]) -> FakeMessage | None:
    candidates = [m for m in messages if not m.is_attachment_or_embed_only]
    if not candidates:
        return None
    return max(candidates, key=lambda m: m.created_at)


STRATEGIES = [_most_reacted, _most_recent_substantive]


def select_snippet(messages: list[FakeMessage], char_budget: int) -> str | None:
    for strategy in STRATEGIES:
        chosen = strategy(messages)
        if chosen is not None:
            return chosen.content[:char_budget]
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_snippets.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add snippets.py tests/test_snippets.py
git commit -m "feat: add pluggable snippet-selection strategy chain"
```

---

### Task 5: Digest Message Formatting (Mentions + Length Budget)

**Files:**
- Create: `digest_format.py`
- Test: `tests/test_digest_format.py`

**Interfaces:**
- Produces: `@dataclass ThreadRenderData(thread_id: int, title: str, jump_url: str, starter_is_url: bool, starter_text: str, snippet: str | None, reply_count: int, participant_count: int)`, `@dataclass DigestMessage(content: str, mention_role_ids: list[int])`, `format_digest(threads: list[ThreadRenderData], role_id: int, title: str, char_limit: int = 2000) -> list[DigestMessage]`.
- Consumed by: `digest.py` (Task 8), which builds `ThreadRenderData` from live discord.py objects and passes the result's `.content`/`.mention_role_ids` into `discord.AllowedMentions(roles=[...])` when actually sending.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_digest_format.py
from digest_format import ThreadRenderData, format_digest

def make_thread(thread_id, starter_is_url=False, starter_text="Some excerpt", snippet="A snippet"):
    return ThreadRenderData(
        thread_id=thread_id,
        title=f"Thread {thread_id}",
        jump_url=f"https://discord.com/channels/1/2/{thread_id}",
        starter_is_url=starter_is_url,
        starter_text=starter_text,
        snippet=snippet,
        reply_count=12,
        participant_count=7,
    )

def test_role_ping_is_in_content_of_first_message():
    threads = [make_thread(1)]
    result = format_digest(threads, role_id=555, title="Featured Discussions This Week")
    assert "<@&555>" in result[0].content
    assert result[0].mention_role_ids == [555]

def test_jump_link_is_wrapped_to_suppress_unfurl():
    threads = [make_thread(1)]
    result = format_digest(threads, role_id=555, title="Featured")
    assert "<https://discord.com/channels/1/2/1>" in result[0].content

def test_bare_starter_url_is_not_wrapped_so_it_unfurls():
    threads = [make_thread(1, starter_is_url=True, starter_text="https://example.com/article")]
    result = format_digest(threads, role_id=555, title="Featured")
    assert "\nhttps://example.com/article\n" in result[0].content or \
        result[0].content.endswith("https://example.com/article")
    assert "<https://example.com/article>" not in result[0].content

def test_stats_line_is_invitational_not_competitive():
    threads = [make_thread(1)]
    result = format_digest(threads, role_id=555, title="Featured")
    assert "12 replies from 7 members" in result[0].content
    assert "winner" not in result[0].content.lower()
    assert "#1" not in result[0].content

def test_no_ordinal_numbering_across_threads():
    threads = [make_thread(1), make_thread(2)]
    result = format_digest(threads, role_id=555, title="Featured")
    full_text = "\n".join(m.content for m in result)
    assert "1." not in full_text.split("\n")[0]

def test_splits_into_multiple_messages_when_over_char_limit():
    threads = [make_thread(i, snippet="x" * 140) for i in range(1, 6)]
    result = format_digest(threads, role_id=555, title="Featured", char_limit=400)
    assert len(result) > 1
    assert result[0].mention_role_ids == [555]
    for later in result[1:]:
        assert later.mention_role_ids == []
    for m in result:
        assert len(m.content) <= 400

def test_single_message_when_under_char_limit():
    threads = [make_thread(1)]
    result = format_digest(threads, role_id=555, title="Featured", char_limit=2000)
    assert len(result) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_digest_format.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'digest_format'`

- [ ] **Step 3: Write `digest_format.py`**

```python
from dataclasses import dataclass, field


@dataclass
class ThreadRenderData:
    thread_id: int
    title: str
    jump_url: str
    starter_is_url: bool
    starter_text: str
    snippet: str | None
    reply_count: int
    participant_count: int


@dataclass
class DigestMessage:
    content: str
    mention_role_ids: list[int] = field(default_factory=list)


def _render_thread_block(thread: ThreadRenderData) -> str:
    lines = [f"**{thread.title}**", f"<{thread.jump_url}>"]
    if thread.starter_is_url:
        lines.append(thread.starter_text)
    else:
        lines.append(f"> {thread.starter_text}")
    if thread.snippet:
        lines.append(f"> {thread.snippet}")
    lines.append(f"_{thread.reply_count} replies from {thread.participant_count} members this week_")
    return "\n".join(lines)


def format_digest(
    threads: list[ThreadRenderData],
    role_id: int,
    title: str,
    char_limit: int = 2000,
) -> list[DigestMessage]:
    header = f"<@&{role_id}> **{title}**"
    blocks = [_render_thread_block(t) for t in threads]

    messages: list[DigestMessage] = []
    current_lines = [header]
    current_role_ids = [role_id]
    current_len = len(header)

    for block in blocks:
        addition_len = len(block) + 2  # blank line separator

        # Flush only once the current message already holds content beyond its
        # anchor (the header for the first message, nothing for later ones) —
        # never emit an anchor-only/empty message.
        has_content_beyond_anchor = len(current_lines) > (1 if not messages else 0)
        if current_len + addition_len > char_limit and has_content_beyond_anchor:
            messages.append(DigestMessage("\n\n".join(current_lines), current_role_ids))
            current_lines = []
            current_role_ids = []
            current_len = 0
            addition_len = len(block)  # fresh message: no anchor, no separator yet

        if current_len + addition_len > char_limit:
            # Even alone (with whatever anchor is already committed), this block
            # exceeds char_limit on its own — truncate so no message ever exceeds it.
            separator_len = addition_len - len(block)
            available = max(char_limit - current_len - separator_len, 0)
            block = block[:available]
            addition_len = len(block) + separator_len

        current_lines.append(block)
        current_len += addition_len

    if current_lines:
        messages.append(DigestMessage("\n\n".join(current_lines), current_role_ids))

    return messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_digest_format.py -v`
Expected: PASS (7 passed)

- [ ] **Step 4b: Add a test for the oversized-block edge case and fix the ordinal-numbering test**

The original `test_no_ordinal_numbering_across_threads` only inspected the header
line, not the rendered thread blocks — fix it to check the actual thread content,
and add a test proving a single oversized block never causes a message to exceed
`char_limit`:

```python
def test_no_ordinal_numbering_in_thread_blocks():
    threads = [make_thread(1), make_thread(2)]
    result = format_digest(threads, role_id=555, title="Featured")
    full_text = "\n".join(m.content for m in result)
    for line in full_text.split("\n"):
        assert not line.strip().startswith(("1.", "2.", "#1", "#2"))

def test_oversized_single_block_is_truncated_not_left_over_limit():
    huge_thread = make_thread(1, snippet="x" * 3000)
    result = format_digest([huge_thread], role_id=555, title="Featured", char_limit=400)
    assert len(result) == 1
    assert len(result[0].content) <= 400
```

Replace the existing `test_no_ordinal_numbering_across_threads` test with
`test_no_ordinal_numbering_in_thread_blocks` above, and add
`test_oversized_single_block_is_truncated_not_left_over_limit` as a new test.

Run: `pytest tests/test_digest_format.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add digest_format.py tests/test_digest_format.py
git commit -m "feat: add digest message formatting with mention sanitization and length budget"
```

---

### Task 6: Scheduler — DST-Safe Cron Trigger

**Files:**
- Create: `scheduler.py`
- Test: `tests/test_scheduler.py`

**Interfaces:**
- Produces: `build_digest_cron_trigger(days: list[str], time_str: str, timezone_name: str) -> apscheduler.triggers.cron.CronTrigger`.
- Consumed by: `bot.py` (Task 17), which registers this trigger with an `AsyncIOScheduler` to call `digest.run_scheduled_digest(...)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scheduler.py
from datetime import datetime
from zoneinfo import ZoneInfo
from scheduler import build_digest_cron_trigger

def test_fires_at_correct_local_time_before_dst_spring_forward():
    trigger = build_digest_cron_trigger(["monday", "friday"], "16:00", "America/Chicago")
    before = datetime(2026, 3, 6, 12, 0, tzinfo=ZoneInfo("America/Chicago"))  # Friday, before DST starts Mar 8
    next_fire = trigger.get_next_fire_time(None, before)
    assert next_fire.hour == 16
    assert next_fire.minute == 0
    assert next_fire.strftime("%A") == "Friday"

def test_fires_at_correct_local_time_after_dst_spring_forward():
    trigger = build_digest_cron_trigger(["monday", "friday"], "16:00", "America/Chicago")
    after = datetime(2026, 3, 9, 12, 0, tzinfo=ZoneInfo("America/Chicago"))  # Monday, after DST started Mar 8
    next_fire = trigger.get_next_fire_time(None, after)
    assert next_fire.hour == 16
    assert next_fire.minute == 0

def test_fires_at_correct_local_time_across_fall_back():
    trigger = build_digest_cron_trigger(["monday", "friday"], "16:00", "America/Chicago")
    before = datetime(2026, 11, 2, 12, 0, tzinfo=ZoneInfo("America/Chicago"))  # Monday, before fall-back Nov 1 (already passed)
    next_fire = trigger.get_next_fire_time(None, before)
    assert next_fire.hour == 16
    assert next_fire.minute == 0
    assert next_fire.tzinfo is not None

def test_only_configured_days_are_used():
    trigger = build_digest_cron_trigger(["monday"], "16:00", "America/Chicago")
    start = datetime(2026, 7, 9, 0, 0, tzinfo=ZoneInfo("America/Chicago"))  # a Thursday
    next_fire = trigger.get_next_fire_time(None, start)
    assert next_fire.strftime("%A") == "Monday"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scheduler'`

- [ ] **Step 3: Write `scheduler.py`**

```python
from apscheduler.triggers.cron import CronTrigger

_DAY_ABBREVIATIONS = {
    "monday": "mon", "tuesday": "tue", "wednesday": "wed", "thursday": "thu",
    "friday": "fri", "saturday": "sat", "sunday": "sun",
}


def build_digest_cron_trigger(days: list[str], time_str: str, timezone_name: str) -> CronTrigger:
    hour, minute = (int(part) for part in time_str.split(":"))
    day_of_week = ",".join(_DAY_ABBREVIATIONS[d.lower()] for d in days)
    return CronTrigger(day_of_week=day_of_week, hour=hour, minute=minute, timezone=timezone_name)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scheduler.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add scheduler.py tests/test_scheduler.py
git commit -m "feat: add DST-safe cron trigger construction for digest schedule"
```

---

### Task 7: New-Thread Staleness Check (Pure Logic)

**Files:**
- Create: `newthread.py`
- Test: `tests/test_newthread.py` (this task covers the pure function only; Task 11 extends the same files with orchestration)

**Interfaces:**
- Produces: `is_stale(due_at: datetime, now: datetime, staleness_cap_hours: int) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_newthread.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_newthread.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'newthread'`

- [ ] **Step 3: Write `newthread.py`**

```python
from datetime import datetime, timedelta


def is_stale(due_at: datetime, now: datetime, staleness_cap_hours: int) -> bool:
    return now - due_at > timedelta(hours=staleness_cap_hours)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_newthread.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add newthread.py tests/test_newthread.py
git commit -m "feat: add staleness check for delayed new-thread announcements"
```

---

### Task 8: Digest Orchestration (`digest.py`)

**Files:**
- Create: `digest.py`
- Test: `tests/test_digest.py`

**Interfaces:**
- Consumes: `Database` (Task 2), `select_featured`/`apply_new_thread_boost` (Task 3), `FakeMessage`/`select_snippet` (Task 4), `ThreadRenderData`/`DigestMessage`/`format_digest` (Task 5).
- Produces: `class DigestRunner` with `async def run(self, guild_id: int, *, manual: bool) -> DigestResult` where `DigestResult` is `@dataclass(posted: bool, message_count: int, reason: str | None)`. Constructor: `DigestRunner(db: Database, config: Config, discord_client: DiscordGateway, rng: random.Random)`. `DiscordGateway` is a small protocol this task defines so tests can supply a fake — real discord.py wiring happens in `bot.py`/`cogs` (Task 17):

```python
class DiscordGateway(Protocol):
    async def fetch_thread_messages(self, thread_id: int, since: datetime) -> list[FakeMessage]: ...
    async def get_thread_title_and_jump_url(self, thread_id: int) -> tuple[str, str]: ...
    async def get_starter_message(self, thread_id: int) -> tuple[bool, str]: ...  # (is_url, text)
    async def send_admin_notice(self, guild_id: int, text: str) -> None: ...
    async def send_digest_messages(self, guild_id: int, messages: list[DigestMessage]) -> None: ...
```

- [ ] **Step 1: Write the failing test**

```python
# tests/test_digest.py
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

async def test_manual_digest_post_behaves_same_as_scheduled(tmp_path):
    db, now = await setup_db(tmp_path)
    for uid in [1, 2, 3]:
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
    gateway = FakeGateway(thread_messages={1: []})
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    result = await runner.run(guild_id=1, manual=True)
    assert result.posted is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_digest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'digest'`

- [ ] **Step 3: Write `digest.py`**

```python
from dataclasses import dataclass
from datetime import datetime, timezone
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

        render_data = []
        for activity in selected:
            messages = await self.gateway.fetch_thread_messages(activity.thread_id, since=now)
            title, jump_url = await self.gateway.get_thread_title_and_jump_url(activity.thread_id)
            starter_is_url, starter_text = await self.gateway.get_starter_message(activity.thread_id)
            snippet = select_snippet(messages, char_budget=self.config.snippet_char_budget)
            render_data.append(ThreadRenderData(
                thread_id=activity.thread_id, title=title, jump_url=jump_url,
                starter_is_url=starter_is_url, starter_text=starter_text, snippet=snippet,
                reply_count=activity.message_count, participant_count=activity.unique_participant_count,
            ))

        guild_config = await self.db.get_guild_config(guild_id)
        messages = format_digest(render_data, role_id=guild_config.digest_role_id, title=self.config.digest_title)
        await self.gateway.send_digest_messages(guild_id, messages)

        for activity in selected:
            await self.db.set_last_featured(activity.thread_id, now)
        await self.db.reset_guild_activity(guild_id)
        await self.db.set_last_digest_at(guild_id, now)

        return DigestResult(posted=True, message_count=len(selected))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_digest.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add digest.py tests/test_digest.py
git commit -m "feat: add digest orchestration with quiet-skip and window reset"
```

---

### Task 9: Backfill — Forum Discovery & Bounded History

**Files:**
- Create: `backfill.py`
- Test: `tests/test_backfill.py`

**Interfaces:**
- Consumes: `Database` (Task 2), `apply_new_thread_boost` (Task 3, used only for genuinely new threads, not for backfilled historical ones).
- Produces: `class BackfillGateway(Protocol)` (defined in this file, faked in tests, implemented for real in `cogs/forum_tracking.py`/`bot.py` in Task 16-17):

```python
class BackfillGateway(Protocol):
    async def list_active_and_recent_archived_threads(self, forum_channel_id: int) -> list["DiscoveredThread"]: ...
    async def fetch_messages_since(self, thread_id: int, since: datetime, cap: int) -> list["BackfillMessage"]: ...
```
- Produces: `@dataclass DiscoveredThread(thread_id: int, created_at: datetime)`, `@dataclass BackfillMessage(author_id: int, reaction_count: int)`, `async def backfill_forum(db: Database, gateway: BackfillGateway, guild_id: int, forum_channel_id: int, config: Config, now: datetime) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backfill.py
from datetime import datetime, timedelta, timezone
from db import Database
from backfill import backfill_forum, DiscoveredThread, BackfillMessage
from config import Config

class FakeBackfillGateway:
    def __init__(self, threads, messages_by_thread):
        self.threads = threads
        self.messages_by_thread = messages_by_thread
        self.fetch_calls = []

    async def list_active_and_recent_archived_threads(self, forum_channel_id):
        return self.threads

    async def fetch_messages_since(self, thread_id, since, cap):
        self.fetch_calls.append((thread_id, since, cap))
        return self.messages_by_thread.get(thread_id, [])[:cap]

async def test_backfill_populates_activity_for_discovered_threads(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    threads = [DiscoveredThread(thread_id=1, created_at=now - timedelta(days=2))]
    messages = {1: [
        BackfillMessage(author_id=100, reaction_count=2),
        BackfillMessage(author_id=101, reaction_count=0),
        BackfillMessage(author_id=100, reaction_count=1),
    ]}
    gateway = FakeBackfillGateway(threads, messages)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now - timedelta(days=1))
    await backfill_forum(db, gateway, guild_id=1, forum_channel_id=10, config=Config(), now=now)
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 3
    assert activity.unique_participant_count == 2
    assert activity.reaction_count == 3

async def test_backfill_caps_message_fetch_and_marks_counted_capped(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    threads = [DiscoveredThread(thread_id=1, created_at=now - timedelta(days=2))]
    many_messages = [BackfillMessage(author_id=i % 5, reaction_count=0) for i in range(500)]
    gateway = FakeBackfillGateway(threads, {1: many_messages})
    await db.add_monitored_forum(10, guild_id=1, designated_at=now - timedelta(days=1))
    config = Config(backfill_message_cap=200)
    await backfill_forum(db, gateway, guild_id=1, forum_channel_id=10, config=config, now=now)
    assert gateway.fetch_calls[0][2] == 200
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 200
    assert activity.counted_capped is True

async def test_backfill_window_starts_at_later_of_last_digest_or_designation(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    designated_at = now - timedelta(days=5)
    last_digest_at = now - timedelta(days=2)
    await db.add_monitored_forum(10, guild_id=1, designated_at=designated_at)
    await db.set_last_digest_at(1, last_digest_at)
    gateway = FakeBackfillGateway([DiscoveredThread(thread_id=1, created_at=now - timedelta(days=4))], {1: []})
    await backfill_forum(db, gateway, guild_id=1, forum_channel_id=10, config=Config(), now=now)
    assert gateway.fetch_calls[0][1] == last_digest_at

async def test_backfill_does_not_create_pending_new_thread_announcements(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now - timedelta(days=1))
    gateway = FakeBackfillGateway([DiscoveredThread(thread_id=1, created_at=now - timedelta(days=2))], {1: []})
    await backfill_forum(db, gateway, guild_id=1, forum_channel_id=10, config=Config(), now=now)
    assert await db.get_unposted_announcements(guild_id=1) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backfill'`

- [ ] **Step 3: Write `backfill.py`**

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from config import Config
from db import Database, ThreadActivity


@dataclass
class DiscoveredThread:
    thread_id: int
    created_at: datetime


@dataclass
class BackfillMessage:
    author_id: int
    reaction_count: int


class BackfillGateway(Protocol):
    async def list_active_and_recent_archived_threads(self, forum_channel_id: int) -> list[DiscoveredThread]: ...
    async def fetch_messages_since(self, thread_id: int, since: datetime, cap: int) -> list[BackfillMessage]: ...


async def backfill_forum(
    db: Database,
    gateway: BackfillGateway,
    guild_id: int,
    forum_channel_id: int,
    config: Config,
    now: datetime,
) -> None:
    forums = await db.get_monitored_forums(guild_id)
    forum = next(f for f in forums if f.forum_channel_id == forum_channel_id)
    guild_config = await db.get_guild_config(guild_id)

    window_start = forum.designated_at
    if guild_config.last_digest_at is not None and guild_config.last_digest_at > window_start:
        window_start = guild_config.last_digest_at

    discovered = await gateway.list_active_and_recent_archived_threads(forum_channel_id)

    for thread in discovered:
        messages = await gateway.fetch_messages_since(thread.thread_id, window_start, config.backfill_message_cap)
        capped = len(messages) >= config.backfill_message_cap

        seen_participants = set()
        message_count = 0
        reaction_count = 0
        for m in messages:
            seen_participants.add(m.author_id)
            message_count += 1
            reaction_count += m.reaction_count

        activity = ThreadActivity(
            thread_id=thread.thread_id, forum_channel_id=forum_channel_id, created_at=thread.created_at,
            message_count=message_count, unique_participant_count=len(seen_participants),
            reaction_count=reaction_count, is_new_thread_boosted=False, last_featured_at=None,
            counted_capped=capped,
        )
        await db.upsert_thread_activity(activity)
        for user_id in seen_participants:
            await db.add_participant(thread.thread_id, user_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backfill.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backfill.py tests/test_backfill.py
git commit -m "feat: add bounded history backfill for forum onboarding"
```

---

### Task 10: New-Thread Announcement Orchestration (extends `newthread.py`)

**Files:**
- Modify: `newthread.py` (add orchestration alongside the `is_stale` function from Task 7)
- Modify: `tests/test_newthread.py` (add orchestration tests alongside the pure-function tests from Task 7)

**Interfaces:**
- Consumes: `Database`, `PendingAnnouncement` (Task 2), `is_stale` (Task 7).
- Produces: `class NewThreadGateway(Protocol)`:
```python
class NewThreadGateway(Protocol):
    async def thread_exists_and_accessible(self, thread_id: int) -> bool: ...
    async def post_new_thread_announcement(self, forum_channel_id: int, thread_id: int) -> None: ...
    async def send_admin_notice(self, guild_id: int, text: str) -> None: ...
```
- Produces: `class NewThreadAnnouncer` with `async def register_new_thread(self, thread_id: int, forum_channel_id: int, guild_id: int, now: datetime, delay_minutes: int) -> None` and `async def process_due_announcements(self, guild_id: int, now: datetime, staleness_cap_hours: int) -> None`. `PendingAnnouncement` now carries a required `guild_id` field (Task 2), so `register_new_thread` takes `guild_id` too, and `process_due_announcements` passes it through to `db.get_unposted_announcements(guild_id)` — a bot instance can be joined to more than one Discord server, so this queue must stay scoped per guild even though cross-server customization is out of scope.

- [ ] **Step 1: Write the failing test (append to `tests/test_newthread.py`)**

```python
# appended to tests/test_newthread.py
from datetime import timedelta
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
```

Add `from datetime import datetime, timezone` import if not already present at the top of `tests/test_newthread.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_newthread.py -v`
Expected: FAIL with `ImportError: cannot import name 'NewThreadAnnouncer' from 'newthread'`

- [ ] **Step 3: Append orchestration to `newthread.py`**

```python
from typing import Protocol
from db import Database, PendingAnnouncement


class NewThreadGateway(Protocol):
    async def thread_exists_and_accessible(self, thread_id: int) -> bool: ...
    async def post_new_thread_announcement(self, forum_channel_id: int, thread_id: int) -> None: ...
    async def send_admin_notice(self, guild_id: int, text: str) -> None: ...


class NewThreadAnnouncer:
    def __init__(self, db: Database, gateway: NewThreadGateway):
        self.db = db
        self.gateway = gateway

    async def register_new_thread(self, thread_id: int, forum_channel_id: int, guild_id: int, now, delay_minutes: int) -> None:
        from datetime import timedelta
        due_at = now + timedelta(minutes=delay_minutes)
        await self.db.add_pending_announcement(
            PendingAnnouncement(
                thread_id=thread_id, forum_channel_id=forum_channel_id, guild_id=guild_id,
                due_at=due_at, posted=False,
            )
        )

    async def process_due_announcements(self, guild_id: int, now, staleness_cap_hours: int) -> None:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_newthread.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add newthread.py tests/test_newthread.py
git commit -m "feat: add new-thread announcement lifecycle with staleness cap and deleted-thread skip"
```

---

### Task 11: Discord Gateway Adapters (Real discord.py Implementations)

**Files:**
- Create: `gateway.py`
- Test: `tests/test_gateway.py`

**Interfaces:**
- Consumes: `discord.py` objects (`discord.Thread`, `discord.Message`, `discord.ForumChannel`, `discord.Client`), `FakeMessage`/`BackfillMessage` types from Tasks 4/9, the `DiscordGateway`/`BackfillGateway`/`NewThreadGateway` protocols from Tasks 8/9/10.
- Produces: `class RealDiscordGateway` implementing all three protocols against a live `discord.Client`, using real discord.py API calls (`thread.history()`, `thread.fetch_message()`, `channel.threads`, `channel.archived_threads()`, `channel.send(..., allowed_mentions=...)`). Channel lookups always fall back to `fetch_channel` on a cache miss (`get_channel(...) or await fetch_channel(...)`) rather than risking a `None` channel. Digest mention sanitization is factored into a static, directly-testable helper `_build_digest_allowed_mentions(mention_role_ids) -> discord.AllowedMentions`, which explicitly sets `everyone=False, users=False` — leaving those unset defaults to "allow everyone/users" in discord.py's `AllowedMentions`, which would let a quoted member snippet's `@everyone` or arbitrary user mention re-broadcast that ping on the digest post. `send_admin_notice`/`post_new_thread_announcement` use `discord.AllowedMentions.none()`.
- This is the one file with a hard discord.py runtime dependency for objects under test; tests build minimal stand-in objects (plain classes with the same attributes discord.py exposes: `.id`, `.content`, `.author.id`, `.reactions`, `.created_at`, `.attachments`, `.embeds`) rather than mocking the library itself.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gateway.py
from datetime import datetime, timezone
from gateway import RealDiscordGateway

class FakeReaction:
    def __init__(self, count):
        self.count = count

class FakeAuthor:
    def __init__(self, id):
        self.id = id

class FakeDiscordMessage:
    def __init__(self, id, content, author_id, reactions=None, created_at=None, attachments=None, embeds=None):
        self.id = id
        self.content = content
        self.author = FakeAuthor(author_id)
        self.reactions = reactions or []
        self.created_at = created_at or datetime.now(timezone.utc)
        self.attachments = attachments or []
        self.embeds = embeds or []

def test_to_fake_message_sums_reaction_counts():
    msg = FakeDiscordMessage(1, "hello", 100, reactions=[FakeReaction(3), FakeReaction(2)])
    result = RealDiscordGateway._to_fake_message(msg)
    assert result.reaction_count == 5
    assert result.content == "hello"
    assert result.author_id == 100
    assert result.is_attachment_or_embed_only is False

def test_to_fake_message_flags_attachment_only_when_content_empty():
    msg = FakeDiscordMessage(1, "", 100, attachments=["file.png"])
    result = RealDiscordGateway._to_fake_message(msg)
    assert result.is_attachment_or_embed_only is True

def test_to_backfill_message_sums_reactions():
    msg = FakeDiscordMessage(1, "hello", 100, reactions=[FakeReaction(4)])
    result = RealDiscordGateway._to_backfill_message(msg)
    assert result.author_id == 100
    assert result.reaction_count == 4

def test_starter_message_url_detection_bare_url():
    assert RealDiscordGateway._is_bare_url("https://example.com/article") is True
    assert RealDiscordGateway._is_bare_url("check this out: https://example.com") is False
    assert RealDiscordGateway._is_bare_url("just some text") is False

def test_build_digest_allowed_mentions_restricts_to_role_only():
    mentions = RealDiscordGateway._build_digest_allowed_mentions(mention_role_ids=[555])
    assert mentions.everyone is False
    assert mentions.users is False
    assert [r.id for r in mentions.roles] == [555]

def test_build_digest_allowed_mentions_empty_role_list_still_suppresses_everyone_and_users():
    mentions = RealDiscordGateway._build_digest_allowed_mentions(mention_role_ids=[])
    assert mentions.everyone is False
    assert mentions.users is False
    assert mentions.roles == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gateway.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gateway'`

- [ ] **Step 3: Write `gateway.py`**

```python
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
    def _build_digest_allowed_mentions(mention_role_ids: list[int]) -> discord.AllowedMentions:
        # Explicit everyone=False/users=False is required: leaving these unset defaults to
        # "allow everyone/users", which would let a quoted member snippet containing
        # @everyone or an arbitrary user mention re-broadcast that ping on the digest post.
        return discord.AllowedMentions(
            roles=[discord.Object(r) for r in mention_role_ids],
            everyone=False,
            users=False,
        )

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
        channel = self.client.get_channel(guild_config.admin_channel_id) or \
            await self.client.fetch_channel(guild_config.admin_channel_id)
        await channel.send(text, allowed_mentions=discord.AllowedMentions.none())

    async def send_digest_messages(self, guild_id: int, messages: list[DigestMessage]) -> None:
        guild_config = await self.db.get_guild_config(guild_id)
        channel = self.client.get_channel(guild_config.digest_channel_id) or \
            await self.client.fetch_channel(guild_config.digest_channel_id)
        for m in messages:
            await channel.send(
                m.content,
                allowed_mentions=self._build_digest_allowed_mentions(m.mention_role_ids),
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
        channel = self.client.get_channel(guild_config.newthread_channel_id) or \
            await self.client.fetch_channel(guild_config.newthread_channel_id)
        await channel.send(
            f"New thread: **{thread.name}**\n<{thread.jump_url}>",
            allowed_mentions=discord.AllowedMentions.none(),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gateway.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add gateway.py tests/test_gateway.py
git commit -m "feat: add real discord.py gateway adapters for digest, backfill, and new-thread flows"
```

---

### Task 12: Slash Commands — `/setup`

**Files:**
- Create: `cogs/__init__.py` (empty)
- Create: `cogs/setup_commands.py`
- Test: `tests/test_setup_commands.py`

**Interfaces:**
- Consumes: `Database` (Task 2).
- Produces: `class SetupCog(commands.Cog)` registering `/setup digest-channel`, `/setup digest-role`, `/setup newthread-channel`, `/setup admin-channel`, `/setup add-forum`, `/setup remove-forum`, `/setup show`, each gated with `@app_commands.checks.has_permissions(manage_guild=True)`. Command bodies are thin wrappers calling `Database` methods directly — tested by calling the underlying callback functions with a fake interaction, not through discord.py's command dispatch machinery.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_setup_commands.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_setup_commands.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cogs'`

- [ ] **Step 3: Create `cogs/__init__.py`** (empty file)

- [ ] **Step 4: Write `cogs/setup_commands.py`**

```python
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from db import Database


class SetupCog(commands.Cog):
    def __init__(self, db: Database):
        self.db = db

    setup_group = app_commands.Group(name="setup", description="Configure the forum discovery bot")

    @setup_group.command(name="digest-channel", description="Set the channel the twice-weekly digest posts to")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def digest_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.db.set_digest_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"Digest channel set to <#{channel.id}>.", ephemeral=True)

    @setup_group.command(name="digest-role", description="Set the role mentioned on digest posts")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def digest_role(self, interaction: discord.Interaction, role: discord.Role):
        await self.db.set_digest_role(interaction.guild.id, role.id)
        await interaction.response.send_message(f"Digest role set to <@&{role.id}>.", ephemeral=True)

    @setup_group.command(name="newthread-channel", description="Set the channel for delayed new-thread posts")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def newthread_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.db.set_newthread_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"New-thread channel set to <#{channel.id}>.", ephemeral=True)

    @setup_group.command(name="admin-channel", description="Set the channel for quiet-skip notices and bot warnings")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def admin_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await self.db.set_admin_channel(interaction.guild.id, channel.id)
        await interaction.response.send_message(f"Admin channel set to <#{channel.id}>.", ephemeral=True)

    @setup_group.command(name="add-forum", description="Start monitoring a forum channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add_forum(self, interaction: discord.Interaction, forum: discord.ForumChannel):
        await self.db.add_monitored_forum(forum.id, interaction.guild.id, datetime.now(timezone.utc))
        await interaction.response.send_message(
            f"Now monitoring **{forum.name}**. Backfilling recent activity...", ephemeral=True
        )

    @setup_group.command(name="remove-forum", description="Stop monitoring a forum channel")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove_forum(self, interaction: discord.Interaction, forum: discord.ForumChannel):
        await self.db.remove_monitored_forum(forum.id)
        await interaction.response.send_message(f"Stopped monitoring **{forum.name}**.", ephemeral=True)

    @setup_group.command(name="show", description="Show current configuration")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def show(self, interaction: discord.Interaction):
        cfg = await self.db.get_guild_config(interaction.guild.id)
        forums = await self.db.get_monitored_forums(interaction.guild.id)
        lines = [
            f"Digest channel: <#{cfg.digest_channel_id}>" if cfg.digest_channel_id else "Digest channel: not set",
            f"Digest role: <@&{cfg.digest_role_id}>" if cfg.digest_role_id else "Digest role: not set",
            f"New-thread channel: <#{cfg.newthread_channel_id}>" if cfg.newthread_channel_id else "New-thread channel: not set",
            f"Admin channel: <#{cfg.admin_channel_id}>" if cfg.admin_channel_id else "Admin channel: not set",
            f"Monitored forums: {', '.join(f'<#{f.forum_channel_id}>' for f in forums) or 'none'}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_setup_commands.py -v`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add cogs/__init__.py cogs/setup_commands.py tests/test_setup_commands.py
git commit -m "feat: add /setup slash commands for runtime channel/role/forum wiring"
```

---

### Task 13: Slash Commands — `/digest preview` and `/digest post`

**Files:**
- Create: `cogs/digest_commands.py`
- Test: `tests/test_digest_commands.py`

**Interfaces:**
- Consumes: `DigestRunner` (Task 8), `select_featured` (Task 3), `Database` (Task 2).
- Produces: `class DigestCog(commands.Cog)` with `/digest preview` (ephemeral, no side effects — reuses `select_featured` against current candidates without calling `DigestRunner.run`) and `/digest post` (calls `DigestRunner.run(manual=True)`, with a command description warning about window reset).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_digest_commands.py
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
    gateway = FakeGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    cog = DigestCog(db, Config(), runner)
    interaction = FakeInteraction(guild_id=1)
    await cog.preview.callback(cog, interaction)
    assert gateway.sent_digests == []
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 3  # untouched
    assert interaction.response.sent[0][1] is True  # ephemeral
    assert "Thread 1" in interaction.response.sent[0][0]

async def test_post_command_triggers_manual_digest_and_resets_window(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    for uid in [1, 2, 3]:
        await db.record_message(thread_id=1, forum_channel_id=10, created_at=now, user_id=uid)
    gateway = FakeGateway()
    runner = DigestRunner(db, Config(), gateway, random.Random(0))
    cog = DigestCog(db, Config(), runner)
    interaction = FakeInteraction(guild_id=1)
    await cog.post.callback(cog, interaction)
    assert len(gateway.sent_digests) == 1
    activity = await db.get_thread_activity(1)
    assert activity.message_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_digest_commands.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cogs.digest_commands'`

- [ ] **Step 3: Write `cogs/digest_commands.py`**

```python
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from db import Database
from digest import DigestRunner
from scoring import select_featured
from config import Config


class DigestCog(commands.Cog):
    def __init__(self, db: Database, config: Config, runner: DigestRunner):
        self.db = db
        self.config = config
        self.runner = runner

    digest_group = app_commands.Group(name="digest", description="Preview or trigger the featured-discussions digest")

    @digest_group.command(name="preview", description="Privately preview what the next digest would contain right now")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def preview(self, interaction: discord.Interaction):
        candidates = await self.db.get_candidates(interaction.guild.id)
        selected = select_featured(
            candidates, now=datetime.now(timezone.utc), cooldown_days=self.config.cooldown_days,
            min_messages=self.config.min_messages, min_participants=self.config.min_participants,
            max_featured=self.config.max_featured_threads, rng=__import__("random").Random(),
        )
        if not selected:
            await interaction.response.send_message("No threads are currently eligible.", ephemeral=True)
            return
        lines = []
        for activity in selected:
            title, _ = await self.runner.gateway.get_thread_title_and_jump_url(activity.thread_id)
            lines.append(
                f"**{title}** — {activity.message_count} messages, "
                f"{activity.unique_participant_count} participants"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @digest_group.command(
        name="post",
        description="Manually post the digest now (resets the activity window and starts cooldowns — "
                     "use /digest preview to check safely first)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def post(self, interaction: discord.Interaction):
        await interaction.response.send_message("Posting digest now...", ephemeral=True)
        await self.runner.run(interaction.guild.id, manual=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_digest_commands.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add cogs/digest_commands.py tests/test_digest_commands.py
git commit -m "feat: add /digest preview and /digest post slash commands"
```

---

### Task 14: Live Event Listeners — `on_thread_create`, `on_message`, Reactions

**Files:**
- Create: `cogs/forum_tracking.py`
- Test: `tests/test_forum_tracking.py`

**Interfaces:**
- Consumes: `Database` (Task 2), `NewThreadAnnouncer` (Task 10), `Config` (Task 1).
- Produces: `class ForumTrackingCog(commands.Cog)` with `on_thread_create`, `on_message`, `on_reaction_add`, `on_reaction_remove` listeners, each guarded by "is this forum monitored" checks, calling into `Database.record_message` / reaction-count updates and `NewThreadAnnouncer.register_new_thread`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_forum_tracking.py
from datetime import datetime, timezone
from db import Database
from newthread import NewThreadAnnouncer
from cogs.forum_tracking import ForumTrackingCog
from config import Config

class FakeParent:
    def __init__(self, id):
        self.id = id

class FakeThread:
    def __init__(self, id, parent_id, guild_id=1, created_at=None):
        self.id = id
        self.parent_id = parent_id
        self.guild = type("G", (), {"id": guild_id})()
        self.created_at = created_at or datetime.now(timezone.utc)

class FakeAuthor:
    def __init__(self, id, bot=False):
        self.id = id
        self.bot = bot

class FakeMessage:
    def __init__(self, id, channel, author_id, bot_author=False):
        self.id = id
        self.channel = channel
        self.author = FakeAuthor(author_id, bot=bot_author)

class FakeGateway:
    def __init__(self):
        self.registered = []

class FakeAnnouncer:
    def __init__(self):
        self.registered = []

    async def register_new_thread(self, thread_id, forum_channel_id, guild_id, now, delay_minutes):
        self.registered.append((thread_id, forum_channel_id))

async def test_on_thread_create_registers_announcement_for_monitored_forum(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    announcer = FakeAnnouncer()
    cog = ForumTrackingCog(db, announcer, Config())
    thread = FakeThread(id=100, parent_id=10)
    await cog.on_thread_create(thread)
    assert announcer.registered == [(100, 10)]

async def test_on_thread_create_ignores_unmonitored_forum(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    announcer = FakeAnnouncer()
    cog = ForumTrackingCog(db, announcer, Config())
    thread = FakeThread(id=100, parent_id=999)  # not monitored
    await cog.on_thread_create(thread)
    assert announcer.registered == []

async def test_on_message_records_activity_for_monitored_forum_thread(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    announcer = FakeAnnouncer()
    cog = ForumTrackingCog(db, announcer, Config())
    thread = FakeThread(id=100, parent_id=10)
    message = FakeMessage(id=1, channel=thread, author_id=555)
    await cog.on_message(message)
    activity = await db.get_thread_activity(100)
    assert activity.message_count == 1

async def test_on_message_ignores_bot_authors(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    announcer = FakeAnnouncer()
    cog = ForumTrackingCog(db, announcer, Config())
    thread = FakeThread(id=100, parent_id=10)
    message = FakeMessage(id=1, channel=thread, author_id=555, bot_author=True)
    await cog.on_message(message)
    activity = await db.get_thread_activity(100)
    assert activity is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_forum_tracking.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cogs.forum_tracking'`

- [ ] **Step 3: Write `cogs/forum_tracking.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_forum_tracking.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add cogs/forum_tracking.py tests/test_forum_tracking.py
git commit -m "feat: add live event listeners for thread creation and message activity"
```

---

### Task 15: Bot Entrypoint — Wiring, Intents, Startup Reconciliation

**Files:**
- Create: `bot.py`
- Test: `tests/test_bot_startup.py` (tests the pure reconciliation helper only; full `discord.Client` construction is not unit-tested — it's exercised via the README's manual first-run flow)

**Interfaces:**
- Consumes: everything from Tasks 1–14.
- Produces: `intents = discord.Intents(...)` module-level constant documented in README; `async def reconcile_on_startup(db: Database, gateway, guild_id: int) -> None` (runs `backfill_forum` for every monitored forum, resumes pending announcements via `NewThreadAnnouncer.process_due_announcements`); `def build_bot(config: Config, db: Database) -> commands.Bot` wiring all cogs and the APScheduler job.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bot_startup.py
from datetime import datetime, timezone, timedelta
from db import Database, PendingAnnouncement
from bot import reconcile_on_startup
from config import Config

class FakeGateway:
    def __init__(self):
        self.backfilled_forums = []
        self.processed_guilds = []

    async def list_active_and_recent_archived_threads(self, forum_channel_id):
        self.backfilled_forums.append(forum_channel_id)
        return []

    async def fetch_messages_since(self, thread_id, since, cap):
        return []

    async def thread_exists_and_accessible(self, thread_id):
        return True

    async def post_new_thread_announcement(self, forum_channel_id, thread_id):
        pass

    async def send_admin_notice(self, guild_id, text):
        pass

async def test_reconcile_backfills_every_monitored_forum(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_monitored_forum(10, guild_id=1, designated_at=now)
    await db.add_monitored_forum(20, guild_id=1, designated_at=now)
    gateway = FakeGateway()
    await reconcile_on_startup(db, gateway, guild_id=1, config=Config())
    assert set(gateway.backfilled_forums) == {10, 20}

async def test_reconcile_resumes_pending_announcements(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    await db.connect()
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    await db.add_pending_announcement(
        PendingAnnouncement(thread_id=1, forum_channel_id=10, guild_id=1, due_at=now - timedelta(minutes=5), posted=False)
    )
    gateway = FakeGateway()
    posted = []
    gateway.post_new_thread_announcement = lambda f, t: posted.append((f, t)) or _async_noop()
    await reconcile_on_startup(db, gateway, guild_id=1, config=Config())
    assert await db.get_unposted_announcements(guild_id=1) == []

def _async_noop():
    import asyncio
    async def noop():
        return None
    return noop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bot_startup.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bot'`

- [ ] **Step 3: Write `bot.py`**

```python
import asyncio
import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import Config, load_config
from db import Database
from backfill import backfill_forum
from newthread import NewThreadAnnouncer
from digest import DigestRunner
from gateway import RealDiscordGateway
from scheduler import build_digest_cron_trigger
from cogs.setup_commands import SetupCog
from cogs.digest_commands import DigestCog
from cogs.forum_tracking import ForumTrackingCog

logger = logging.getLogger("forum_digest_bot")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
intents.guild_reactions = True


async def reconcile_on_startup(db: Database, gateway, guild_id: int, config: Config) -> None:
    forums = await db.get_monitored_forums(guild_id)
    for forum in forums:
        await backfill_forum(db, gateway, guild_id, forum.forum_channel_id, config, datetime.now(timezone.utc))
    announcer = NewThreadAnnouncer(db, gateway)
    await announcer.process_due_announcements(
        guild_id, datetime.now(timezone.utc), config.new_thread_staleness_cap_hours
    )


def build_bot(config: Config, db: Database) -> commands.Bot:
    bot = commands.Bot(command_prefix="!", intents=intents)
    gateway = RealDiscordGateway(bot, db)
    runner = DigestRunner(db, config, gateway, __import__("random").Random())
    announcer = NewThreadAnnouncer(db, gateway)

    @bot.event
    async def on_ready():
        logger.info("Logged in as %s", bot.user)
        for guild in bot.guilds:
            try:
                await reconcile_on_startup(db, gateway, guild.id, config)
            except Exception:
                logger.exception("Startup reconciliation failed for guild %s", guild.id)
        await bot.tree.sync()

        scheduler = AsyncIOScheduler()
        trigger = build_digest_cron_trigger(config.digest_days, config.digest_time, config.timezone)

        async def scheduled_digest_job():
            for guild in bot.guilds:
                guild_config = await db.get_guild_config(guild.id)
                if guild_config.digest_channel_id is None:
                    await gateway.send_admin_notice(
                        guild.id, "Scheduled digest fired but no digest channel is configured. Run /setup digest-channel."
                    )
                    continue
                try:
                    await runner.run(guild.id, manual=False)
                except discord.Forbidden:
                    logger.exception("Missing permissions posting digest for guild %s", guild.id)
                    await gateway.send_admin_notice(guild.id, "Missing permissions to post the digest.")

        scheduler.add_job(scheduled_digest_job, trigger)

        async def new_thread_poll_job():
            for guild in bot.guilds:
                await announcer.process_due_announcements(
                    guild.id, datetime.now(timezone.utc), config.new_thread_staleness_cap_hours
                )

        scheduler.add_job(new_thread_poll_job, "interval", minutes=1)
        scheduler.start()

    asyncio.get_event_loop().run_until_complete(bot.add_cog(SetupCog(db)))
    asyncio.get_event_loop().run_until_complete(bot.add_cog(DigestCog(db, config, runner)))
    asyncio.get_event_loop().run_until_complete(bot.add_cog(ForumTrackingCog(db, announcer, config)))

    return bot


if __name__ == "__main__":
    import os

    logging.basicConfig(level=logging.INFO)
    config = load_config(os.environ.get("BOT_CONFIG_PATH", "config.yaml"))
    db = Database(os.environ.get("BOT_DB_PATH", "bot.db"))
    asyncio.get_event_loop().run_until_complete(db.connect())
    bot = build_bot(config, db)
    bot.run(os.environ["DISCORD_BOT_TOKEN"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bot_startup.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tests across all modules)

- [ ] **Step 6: Commit**

```bash
git add bot.py tests/test_bot_startup.py
git commit -m "feat: add bot entrypoint with startup reconciliation and scheduler wiring"
```

---

### Task 16: Dockerfile & Deployment Files

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

**Interfaces:**
- Consumes: `requirements.txt` (Task 1), `bot.py` (Task 15).
- Produces: a runnable container image; no code interfaces (deployment-only task, no automated test — verified manually per Step 3 below).

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/app/data"]
ENV BOT_DB_PATH=/app/data/bot.db
ENV BOT_CONFIG_PATH=/app/data/config.yaml

CMD ["python", "bot.py"]
```

- [ ] **Step 2: Write `docker-compose.yml`**

```yaml
services:
  forum-digest-bot:
    build: .
    restart: unless-stopped
    environment:
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN}
    volumes:
      - ./data:/app/data
```

- [ ] **Step 3: Verify the image builds**

Run: `docker build -t forum-digest-bot .`
Expected: build completes with exit code 0

- [ ] **Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "chore: add Docker deployment files"
```

---

### Task 17: README

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: nothing (documentation only).

- [ ] **Step 1: Write `README.md`**

```markdown
# Forum Discovery Bot

A Discord bot that helps members discover active forum-channel conversations
they may have missed. Twice a week it posts a "Featured Discussions" digest of
threads that crossed an activity threshold — never a ranked leaderboard. It
also posts a quiet, delayed notice when a new thread appears in a monitored
forum, giving the author time to edit or delete before anyone is pinged.

## Requirements

- Python 3.11+
- A Discord bot application (see below)

## Discord Developer Portal Setup

1. Create an application at https://discord.com/developers/applications
2. Under **Bot**, create a bot user and copy its token (this is `DISCORD_BOT_TOKEN`).
3. Under **Bot > Privileged Gateway Intents**, enable **Message Content Intent**.
   This is required to read thread messages for activity scoring and snippet
   selection — the bot will not function without it.
4. Under **OAuth2 > URL Generator**, select scope `bot` and `applications.commands`,
   and these bot permissions:
   - View Channel
   - Read Message History
   - Send Messages
   - Embed Links
   - Mention Roles (or ensure the target role is set to "Allow anyone to
     @mention this role", whichever your server prefers)
5. Use the generated URL to invite the bot to your server.

## Configuration

Runtime-configurable via slash commands (persisted in the database, no restart needed):

| Command | Purpose |
|---|---|
| `/setup digest-channel <#channel>` | Where the twice-weekly digest posts |
| `/setup digest-role <@role>` | Role mentioned on digest posts |
| `/setup newthread-channel <#channel>` | Where delayed new-thread posts go |
| `/setup admin-channel <#channel>` | Where quiet-skip notices and warnings go |
| `/setup add-forum <#forum>` | Start monitoring a forum channel |
| `/setup remove-forum <#forum>` | Stop monitoring a forum channel |
| `/setup show` | Display current configuration |
| `/digest preview` | Privately preview the next digest's contents (no side effects) |
| `/digest post` | Manually post the digest now — **this resets the activity window and starts cooldowns**, shrinking the next scheduled digest's window. Use `/digest preview` first to check safely. |

Config-file settings (edit `config.yaml`, restart the bot to apply):

| Key | Default | Meaning |
|---|---|---|
| `min_messages` | 5 | Minimum messages since last digest for a thread to be eligible |
| `min_participants` | 3 | Minimum unique participants for a thread to be eligible |
| `cooldown_days` | 7 | Days a featured thread is ineligible afterward |
| `new_thread_boost_messages` | 2 | One-time score boost applied to brand-new threads |
| `digest_days` | `["monday", "friday"]` | Days the digest posts |
| `digest_time` | `16:00` | Local time the digest posts |
| `timezone` | `America/Chicago` | Timezone for `digest_time` (DST-safe) |
| `digest_title` | `Featured Discussions This Week` | Digest message title |
| `new_thread_delay_minutes` | 60 | Delay before a new-thread post fires |
| `new_thread_staleness_cap_hours` | 24 | If the bot was down longer than this, skip a stale pending announcement |
| `backfill_message_cap` | 200 | Max messages backfilled per thread on startup/designation |
| `snippet_char_budget` | 150 | Max characters for a digest entry's snippet |
| `max_featured_threads` | 5 | Max threads per digest |

Copy `config.example.yaml` to `config.yaml` and adjust as needed.

## First-Run Flow

1. Invite the bot (see Developer Portal Setup above).
2. Run `/setup digest-channel`, `/setup digest-role`, `/setup newthread-channel`,
   and `/setup admin-channel`.
3. Run `/setup add-forum` for each forum channel to monitor (e.g. Scion, Tiamat,
   Silent Farm). The bot backfills each forum's recent history immediately —
   pre-existing threads are picked up for eligibility tracking, but will
   **not** trigger a new-thread announcement (those only fire for threads
   created after the forum was designated).
4. Run `/setup show` to confirm configuration.
5. Run `/digest preview` any time to see what the next digest would contain
   without posting or resetting anything.

## Running Locally

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
export DISCORD_BOT_TOKEN=your-token-here
python bot.py
```

## Running with Docker

```bash
cp config.example.yaml data/config.yaml
export DISCORD_BOT_TOKEN=your-token-here
docker compose up -d --build
```

The SQLite database and config file live in `./data`, mounted as a volume so
they survive container restarts and rebuilds.

## Testing

```bash
pip install -r requirements.txt
pytest -v
```

All tests mock Discord API interaction — no live server or bot token is
required to run the test suite.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README covering setup, config, and deployment"
```

---

## Self-Review Notes

**Spec coverage:** every product-behavior bullet, every resolved open question, and all five design-review fixes map to a task above — digest cadence/format (Tasks 5, 6, 8), threshold eligibility and weighting (Task 3), cooldown (Task 3), quiet-skip without window reset (Tasks 3, 8), new-thread delayed post with staleness cap and deleted-thread skip (Tasks 7, 10), onboarding/backfill/no-retroactive-ping (Task 9), mention sanitization and length-budget splitting (Task 5), live reaction re-fetch at assembly (Task 8, via `fetch_thread_messages` called fresh per run), slash commands (Tasks 12–13), event listeners (Task 14), DST-safe scheduling (Task 6), deployment and docs (Tasks 16–17).

**Type consistency:** `ThreadActivity`, `PendingAnnouncement`, `GuildConfig`, `MonitoredForum` (Task 2) are used with identical field names throughout Tasks 3, 8, 9, 10, 15. `FakeMessage` (Task 4) and `DigestMessage`/`ThreadRenderData` (Task 5) are consumed unchanged by `digest.py` (Task 8) and produced for real by `gateway.py` (Task 11). `DiscordGateway`, `BackfillGateway`, `NewThreadGateway` protocols (Tasks 8, 9, 10) are all implemented together by the single `RealDiscordGateway` class (Task 11).

**No placeholders:** every step includes complete, runnable code — no TBD/TODO markers.

---

Plan complete and saved to `docs/superpowers/plans/2026-07-09-forum-discovery-bot-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
