# Forum Discovery Bot — Design Spec

Date: 2026-07-09
Status: Approved for planning

## Purpose

A Discord bot that helps members discover active forum-channel conversations they
may have missed, and encourages participation — explicitly **not** a leaderboard.
Featured threads are framed as "conversations worth checking out," never as
winners or rankings.

## Product Behavior (client-approved, fixed for v1)

### Featured Discussions digest

- Posts twice weekly: Monday and Friday, 4:00 PM, stored as timezone
  `America/Chicago` (DST-safe). Days/time configurable via config file.
- Title: "Featured Discussions This Week" (configurable).
- Up to 5 threads, presented **unranked** — no ordinal numbering, no "winner"
  language, order randomized per post so position never implies rank.
- Posts to an admin-designated text channel, pinging a designated role
  (never `@everyone`). Channel and role are wired at runtime via slash
  commands, not hardcoded.

### Eligibility (threshold, not ranking)

- Score is computed **since the last digest** (a variable-length window,
  typically 3–4 days), anchored on `last_digest_at`.
- Eligible if `message_count >= 5` (default) **and**
  `unique_participant_count >= 3` (default). Both thresholds configurable.
- Unique participants are weighted more heavily than raw message volume, so a
  high-volume two-person exchange doesn't crowd out broader conversations —
  enforced structurally by requiring both thresholds, and by sorting eligible
  candidates on `unique_participant_count` first when more than 5 qualify.
- If more than 5 threads are eligible, the 5 with the broadest participation
  are chosen (sorted by unique participants, then message count, as
  tie-break) — still displayed unranked, in randomized order.
- A featured thread is ineligible for ~7 days afterward (configurable
  cooldown), stamped only when a thread is actually included in a digest.

### Quiet skip

- If no thread crosses the threshold, skip the public post and privately
  notify admins (admin channel or DM).
- **The activity window is NOT cleared on a quiet skip.** Only an actual
  public digest post resets `last_digest_at` and the per-thread counters.
  This lets slow-building conversations accumulate activity across multiple
  quiet cycles instead of being zeroed out every time — otherwise a thread
  with, say, 4 messages from 2 people every cycle could never qualify, which
  would contradict the discovery goal.

### New-thread visibility post (delayed, silent)

- When a new thread is created in a monitored forum, wait 1 hour
  (configurable) before announcing, so the author can edit/delete a mistake.
- When the timer fires: re-fetch the thread; if deleted or inaccessible,
  silently skip.
- **Staleness cap:** if the bot was down and a pending announcement's due
  time is more than 24 hours in the past (configurable) by the time the bot
  resumes, mark it handled without posting publicly, and note the skip in
  the admin channel. Announcing a thread from days ago as "new" would look
  broken.
- Posts to a separate admin-designated channel, no role/user ping. Replies
  from staff/members can organically draw attention.
- New threads get a one-time configurable score boost toward digest
  eligibility so they don't start from zero.

### Digest entry contents

- Thread title + clickable jump link.
- The thread's starter message: if it's a bare URL, placed so Discord
  unfurls it; otherwise a truncated excerpt.
- An enticing snippet, chosen via a pluggable strategy chain: default is
  most-reacted message in the window → most-recent substantive message
  (skipping attachment/embed-only messages) → generic fallback string.
- Light, invitational stats ("12 replies from 7 members this week"), never
  competitive language.

## Open Technical Questions — Resolved

| Question | Decision |
|---|---|
| Runtime | discord.py (mature async ecosystem, native forum-channel-type slash-command filters, pairs cleanly with APScheduler + aiosqlite) |
| Scoring window | Strictly "since last digest," not rolling 7-day. `/digest post` (manual) resets it immediately, same as scheduled. |
| New-thread post vs. digest overlap | Independent — a thread can get both in the same cycle. Only actual digest inclusion starts the 7-day cooldown; the new-thread post is not a "feature." |
| Digest visual format | Plain markdown message (not embeds). Role ping and starter-message URLs must live in message content — mentions inside embeds don't notify, and URLs inside embed descriptions don't unfurl. Jump links are wrapped in `<>` to suppress their own unfurl. |
| Reaction weighting (starter vs. reply) | Equal — all reactions in the window count the same toward the score regardless of which message they're on. |
| Backfill depth cap | Cap at N messages per thread (default 200), fetched newest-first, stop early once well past threshold. Display whatever was actually counted (a true lower bound) rather than an exact count for capped threads. |

## Additional Fixes from Design Review

1. **Mention sanitization (must-fix).** Quoted snippet content is arbitrary
   member text and could contain `@everyone` or role mentions. The digest
   post sets `allowed_mentions=discord.AllowedMentions(roles=[digest_role],
   everyone=False, users=False)`; the new-thread post sets
   `allowed_mentions=discord.AllowedMentions.none()`. This closes an abuse
   vector where a member could get the bot to re-broadcast a ping via a
   reacted-to message.

2. **Message length budget (must-fix).** Five thread entries could exceed
   Discord's 2000-character content limit on a busy week. Snippets are
   truncated to a configurable budget (~150 chars default). At assembly,
   total projected length is computed; if it would exceed the limit, the
   digest splits into a second message, with the role ping only on the
   first message.

3. **Reaction staleness at digest time.** Rolled-up counters (used for
   eligibility scoring) are updated incrementally and may lag live reaction
   changes. Rather than wiring raw per-reaction event tracking, digest
   assembly re-fetches each of the ≤5 featured threads' message windows
   fresh from the API immediately before running snippet selection —
   bounded cost, always-current reactions, and it naturally skips messages
   deleted since backfill.

## Data Model (SQLite via aiosqlite)

```sql
guild_config (
  guild_id INTEGER PRIMARY KEY,
  digest_channel_id INTEGER,
  digest_role_id INTEGER,
  newthread_channel_id INTEGER,
  admin_channel_id INTEGER,
  last_digest_at TIMESTAMP
)

monitored_forums (
  forum_channel_id INTEGER PRIMARY KEY,
  guild_id INTEGER,
  designated_at TIMESTAMP        -- anchors no-retroactive-ping + backfill start
)

thread_activity (
  thread_id INTEGER PRIMARY KEY,
  forum_channel_id INTEGER,
  created_at TIMESTAMP,
  message_count INTEGER,
  unique_participant_count INTEGER,
  reaction_count INTEGER,
  is_new_thread_boosted BOOLEAN,
  last_featured_at TIMESTAMP,    -- NULL if never featured; drives cooldown
  counted_capped BOOLEAN         -- true if backfill hit the depth cap
)

thread_participants (
  thread_id INTEGER,
  user_id INTEGER,
  PRIMARY KEY (thread_id, user_id)
)

pending_newthread_announcements (
  thread_id INTEGER PRIMARY KEY,
  forum_channel_id INTEGER,
  due_at TIMESTAMP,
  posted BOOLEAN DEFAULT FALSE
)
```

`thread_activity` counters reset only on an actual digest post (scheduled or
manual `/digest post`), never on a quiet skip. `last_featured_at` is
independent of that reset and solely drives the 7-day cooldown.

## Module Layout

```
bot.py                  # entrypoint, client setup, intents
config.py               # config-file loading (thresholds, weights, schedule, delays)
db.py                   # aiosqlite schema + queries
cogs/
  setup_commands.py     # /setup ... slash commands
  digest_commands.py    # /digest preview, /digest post
  forum_tracking.py     # on_thread_create, on_message, on_reaction listeners
scoring.py              # eligibility scoring, weighting, cooldown logic
digest.py               # digest assembly + formatting + posting (mention sanitization,
                         # length budget/splitting, live re-fetch for snippets)
newthread.py            # delayed-announcement scheduling, resume-on-startup, staleness cap
snippets.py             # pluggable snippet-selection strategies
backfill.py             # thread discovery + bounded history backfill
scheduler.py            # APScheduler wiring for the twice-weekly cron
```

## Core Workflows

### Digest assembly (scheduled or manual `/digest post`)

1. Query eligible, non-cooldown threads for the guild (window = since
   `last_digest_at`).
2. If none eligible: send admin-channel quiet-skip notice. Do **not** reset
   `last_digest_at` or clear counters.
3. If ≥1 eligible: select up to 5 by broadest-participation rule, in
   randomized display order.
4. For each selected thread: re-fetch its message window live, run snippet
   selection, resolve jump link and starter message/URL, compute stats line.
5. Compose plain-markdown message(s) respecting the length budget (split
   with ping only on message 1), with `allowed_mentions` locked to the
   digest role only.
6. Post to `digest_channel_id`. Stamp `last_featured_at` for included
   threads. Reset `last_digest_at` and clear activity counters for the
   guild's threads.

`/digest post`'s command description and the README both carry an explicit
warning: triggering it mid-week resets the window and starts cooldowns,
shrinking the next scheduled digest's window. Use `/digest preview` (which
has no side effects) to check contents safely.

### New-thread delayed announcement

1. `on_thread_create` (designated forums only) → insert
   `pending_newthread_announcements` row with `due_at = now + delay` →
   immediately apply the one-time score boost.
2. A short-interval in-process check (plus rows loaded and resumed on
   startup) fires each due row: if `due_at` is more than the staleness cap
   in the past, mark `posted = TRUE`, note the skip in the admin channel,
   no public post. Otherwise re-fetch the thread; if deleted/inaccessible,
   mark `posted = TRUE` and skip silently; otherwise post (no ping,
   `allowed_mentions.none()`) to `newthread_channel_id`, then mark posted.

### Forum onboarding (`/setup add-forum`, re-verified every startup)

1. Insert/confirm `monitored_forums` row with `designated_at = now`.
2. Enumerate active threads (plus recently archived) via the API — pure
   discovery, no scoring yet.
3. Backfill messages from `max(last_digest_at, designated_at)` to now,
   capped at 200 messages/thread (default), newest-first, populating
   `thread_activity`/`thread_participants`. Reaction counts read directly
   off fetched message objects.
4. No `pending_newthread_announcements` rows are created for these
   discovered pre-existing threads — only genuine `on_thread_create` events
   (necessarily after `designated_at`) create them. This is what prevents
   retroactive announcement spam when adding a long-running forum.

Archived threads remain tracked in `thread_activity` regardless of archive
state; the startup reconciliation pass includes recently-archived threads in
discovery so auto-archival between digests doesn't drop a thread from
eligibility tracking.

## Discord Integration Specifics

- **Privileged intent:** Message Content Intent (manual Developer Portal
  toggle — documented explicitly in README), plus standard Guilds/Guild
  Messages/Guild Message Reactions intents.
- **Invite permissions:** View Channel, Read Message History, Send Messages,
  Embed Links, Mention Roles (or an explicitly mentionable role — README
  documents both paths).
- **Starter message fetch:** always explicitly fetched
  (`thread.fetch_message(thread.id)`), never assumed to be in cache.
- **Slash command channel filtering:** forum-only channel parameters use
  discord.py's channel-type-constrained parameter types so Discord's UI
  only offers valid channels — no manual validation needed.

## Error Handling & Degradation

- Scheduled digest fires with no `digest_channel_id` configured, or missing
  permissions: log clearly, notify `admin_channel_id` if configured.
- `discord.Forbidden` on any API call: caught at the call site, logged with
  channel/action context, surfaced as an admin notice where relevant — never
  an unhandled crash.
- Rate limits: handled by discord.py's built-in machinery; backfill uses the
  library's async pagination iterators.
- Bot restart mid-cycle: `last_digest_at`, `thread_activity`, and
  `pending_newthread_announcements` all persist in SQLite — a restart never
  loses eligibility or timer state.

## Testing Strategy

All Discord API interaction is mocked — no live server/token required.
Coverage includes: threshold eligibility (boundary cases), unique-participant
weighting, cooldown enforcement across multiple cycles, quiet-skip +
admin-notify path (and that it does *not* clear the window), new-thread score
boost, delayed-announcement lifecycle (normal post, deleted-thread skip,
restart-resume, staleness-cap skip), no-retroactive-ping guard on forum
designation, backfill windowing + depth cap, snippet-selection fallback
chain, live re-fetch at digest assembly, mention sanitization on both post
types, message-length-budget splitting, APScheduler cron correctness across a
DST boundary (`America/Chicago` spring-forward/fall-back dates), and digest
formatting (URL placement/suppression).

## Deployment

Dockerfile (Python slim base; `discord.py`, `aiosqlite`, `apscheduler`), volume-mounted
SQLite file and config file, bot token via environment variable. README
covers: Developer Portal bot creation and enabling Message Content Intent,
invite-link generation with the exact permission set above, and the
first-run flow (invite bot → run `/setup` commands → done).

## Out of Scope for v1 (YAGNI)

- Web dashboard
- Cross-server support
- AI-generated thread summaries
- Historical analytics beyond what eligibility tracking requires
- Editing thresholds/weights/schedule via slash commands (config file +
  restart only; channel/role wiring is the only runtime-configurable part)
