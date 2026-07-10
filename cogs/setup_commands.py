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
