import random
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

    # Discord caps slash-command descriptions at 100 characters
    @digest_group.command(
        name="preview",
        description="Privately render the exact digest message that would post right now (no side effects)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def preview(self, interaction: discord.Interaction):
        selected, messages = await self.runner.build_messages(
            interaction.guild.id, datetime.now(timezone.utc)
        )
        if not selected:
            await interaction.response.send_message("No threads are currently eligible.", ephemeral=True)
            return
        # The rendering includes the role-ping text; disarm it so a preview never pings.
        disarmed = discord.AllowedMentions.none()
        await interaction.response.send_message(
            messages[0].content, ephemeral=True, allowed_mentions=disarmed
        )
        for extra in messages[1:]:
            await interaction.followup.send(extra.content, ephemeral=True, allowed_mentions=disarmed)

    @digest_group.command(
        name="stats",
        description="Show currently eligible threads and their activity stats (no side effects)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def stats(self, interaction: discord.Interaction):
        candidates = await self.db.get_candidates(interaction.guild.id)
        selected = select_featured(
            candidates, now=datetime.now(timezone.utc), cooldown_days=self.config.cooldown_days,
            min_messages=self.config.min_messages, min_participants=self.config.min_participants,
            max_featured=self.config.max_featured_threads, rng=random.Random(),
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
        # Discord caps slash-command descriptions at 100 characters
        description="Post the digest now (resets the window and starts cooldowns - try /digest preview first)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def post(self, interaction: discord.Interaction):
        await interaction.response.send_message("Posting digest now...", ephemeral=True)
        await self.runner.run(interaction.guild.id, manual=True)
