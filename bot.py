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
    bot.scheduler = None  # guards against on_ready firing again after a reconnect
    gateway = RealDiscordGateway(bot, db)
    runner = DigestRunner(db, config, gateway, __import__("random").Random())
    announcer = NewThreadAnnouncer(db, gateway)

    async def scheduled_digest_job():
        for guild in bot.guilds:
            try:
                guild_config = await db.get_guild_config(guild.id)
                if guild_config.digest_channel_id is None:
                    await gateway.send_admin_notice(
                        guild.id, "Scheduled digest fired but no digest channel is configured. Run /setup digest-channel."
                    )
                    continue
                await runner.run(guild.id, manual=False)
            except discord.Forbidden:
                logger.exception("Missing permissions posting digest for guild %s", guild.id)
                await gateway.send_admin_notice(guild.id, "Missing permissions to post the digest.")
            except Exception:
                logger.exception("Scheduled digest job failed for guild %s", guild.id)

    async def new_thread_poll_job():
        for guild in bot.guilds:
            try:
                await announcer.process_due_announcements(
                    guild.id, datetime.now(timezone.utc), config.new_thread_staleness_cap_hours
                )
            except Exception:
                logger.exception("New-thread poll job failed for guild %s", guild.id)

    @bot.event
    async def on_ready():
        logger.info("Logged in as %s", bot.user)
        for guild in bot.guilds:
            try:
                await reconcile_on_startup(db, gateway, guild.id, config)
            except Exception:
                logger.exception("Startup reconciliation failed for guild %s", guild.id)
        await bot.tree.sync()

        # on_ready is not guaranteed to fire only once (discord.py re-fires it after some
        # reconnects) — without this guard, a second firing would start a second
        # concurrent scheduler, double-posting the digest and double-running the poll job.
        if bot.scheduler is not None:
            return

        bot.scheduler = AsyncIOScheduler()
        trigger = build_digest_cron_trigger(config.digest_days, config.digest_time, config.timezone)
        bot.scheduler.add_job(scheduled_digest_job, trigger)
        bot.scheduler.add_job(new_thread_poll_job, "interval", minutes=1)
        bot.scheduler.start()

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
