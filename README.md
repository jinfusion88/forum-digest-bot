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

## Commands

All commands require the **Manage Server** permission. Responses are private
(ephemeral) — only the person running the command sees them. Settings changed
via `/setup` are persisted in the database immediately; no restart needed.

| Command | Function |
|---|---|
| `/setup digest-channel <#channel>` | Set the channel where the twice-weekly Featured Discussions digest posts |
| `/setup digest-role <@role>` | Set the role mentioned (pinged) on digest posts |
| `/setup newthread-channel <#channel>` | Set the channel for delayed, ping-free new-thread announcements |
| `/setup admin-channel <#channel>` | Set the channel for quiet-skip notices and bot warnings |
| `/setup add-forum <#forum>` | Start monitoring a forum channel (activity tracking begins from this moment; no retroactive announcements) |
| `/setup remove-forum <#forum>` | Stop monitoring a forum channel |
| `/setup show` | Display the current configuration (channels, role, monitored forums) |
| `/digest preview` | Render the exact digest message that would post right now — full formatting, snippets, and stats, with the role ping disarmed. No side effects |
| `/digest stats` | List the currently eligible threads with their message and participant counts. No side effects |
| `/digest post` | Post the digest immediately — **resets the activity window and starts featured-thread cooldowns**, shrinking the next scheduled digest's window. Check with `/digest preview` first |

## Configuration

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

## Hosting on Google Cloud

The bot is a long-running gateway process with a local SQLite file, so it needs
an always-on host with a persistent disk. A Compute Engine **e2-micro** VM fits
best — it's covered by GCP's Always Free tier (one per account, in `us-west1`,
`us-central1`, or `us-east1`), and its boot disk persists the SQLite database
across reboots. Cloud Run is **not** a good fit: its filesystem is ephemeral
(the database would vanish on every restart) and scale-to-zero would disconnect
the bot from Discord.

No inbound ports are needed — the bot only makes outbound connections to
Discord — so the default firewall is fine as-is.

### 1. Create the VM

Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install) locally and
authenticate. **Pick your own project ID** everywhere `PROJECT_ID` appears below —
project IDs are globally unique across all of Google Cloud, so a generic name
will already be taken (e.g. use `forum-digest-bot-<yourinitials>`).

> **Windows note:** the `\` line continuations below are bash syntax. In
> `cmd`/PowerShell, run each command on a single line instead.

```bash
gcloud auth login
gcloud projects create PROJECT_ID --name="forum-digest-bot"
gcloud config set project PROJECT_ID
# A billing account must be linked for VM creation (free tier still applies).
# List accounts, then link one:
gcloud billing accounts list
gcloud billing projects link PROJECT_ID --billing-account=BILLING_ACCOUNT_ID
gcloud services enable compute.googleapis.com

gcloud compute instances create forum-digest-bot \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB
```

### 2. Install Docker on the VM

```bash
gcloud compute ssh forum-digest-bot --zone=us-central1-a
```

Then on the VM:

```bash
sudo apt-get update
sudo apt-get install -y docker.io curl git
sudo systemctl enable --now docker
# Debian 12 doesn't package Compose v2 - install the official plugin binary:
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -sSL https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
sudo usermod -aG docker $USER
exit   # log out and back in so the docker group takes effect
```

### 3. Copy the project to the VM

Either clone the repo (for a private repo, use a GitHub fine-grained personal
access token with read-only content access as the password):

```bash
gcloud compute ssh forum-digest-bot --zone=us-central1-a
git clone https://github.com/jinfusion88/forum-digest-bot.git
cd forum-digest-bot
```

...or copy your local working directory up directly:

```bash
gcloud compute scp --recurse --zone=us-central1-a . forum-digest-bot:~/forum-digest-bot
```

### 4. Configure and start the bot

On the VM, in the project directory:

```bash
mkdir -p data && cp config.example.yaml data/config.yaml
echo "DISCORD_BOT_TOKEN=your-token-here" > .env
docker compose up -d --build
```

`docker compose` reads `DISCORD_BOT_TOKEN` from the `.env` file automatically.
The `.env` file is gitignored and never leaves the VM — don't commit it.

The compose file's `restart: unless-stopped` policy plus Docker's systemd unit
mean the bot comes back automatically after a VM reboot or crash — no extra
setup needed.

### 5. Operating the bot

```bash
docker compose logs -f            # follow the bot's logs
docker compose restart           # restart (e.g. after editing data/config.yaml)
git pull && docker compose up -d --build   # deploy an update
```

The SQLite database lives in `~/forum-digest-bot/data/` on the VM's persistent
boot disk. To back it up from your local machine:

```bash
gcloud compute scp --zone=us-central1-a forum-digest-bot:~/forum-digest-bot/data/bot.db ./bot-backup.db
```

## Testing

```bash
pip install -r requirements.txt
pytest -v
```

All tests mock Discord API interaction — no live server or bot token is
required to run the test suite.
