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
mkdir -p data && cp config.example.yaml data/config.yaml
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
