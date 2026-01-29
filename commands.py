"""
Location: /mnt/f/Code/discordbot/commands.py
Summary: Slash command registration and handlers for the Discord bot.
         Contains all app_commands (slash commands) and the global error handler.
         Separated from main.py to reduce file size and improve modularity.

Used by: main.py calls register_commands(bot) after creating the DiscordBot instance.
Uses: utils/text_formatting.py (create_embed), utils/constants.py (MAX_PROMPT_LENGTH),
      session_manager.py (via bot.session_manager).
"""

import logging
from datetime import datetime

import discord
from discord import app_commands

from utils.constants import MAX_PROMPT_LENGTH
from utils.text_formatting import create_embed

logger = logging.getLogger(__name__)


def register_commands(bot) -> None:
    """Register all slash commands on the bot's command tree.

    Separated from bot construction so that module-level import does not
    trigger side effects. Called once from main().

    Args:
        bot: The DiscordBot instance to register commands on.
    """

    @bot.tree.command(name="prof", description="Chat with Professor Synapse")
    @app_commands.checks.cooldown(1, 60)
    async def prof_command(interaction: discord.Interaction, *, prompt: str):
        """Command handler for /prof"""
        # Validate prompt length before sending to external API
        if len(prompt) > MAX_PROMPT_LENGTH:
            error_embed = create_embed(
                title="Prompt Too Long",
                description=(
                    f"Your prompt is {len(prompt)} characters. "
                    f"Please keep it under {MAX_PROMPT_LENGTH} characters."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        await bot.prof(interaction, prompt=prompt)

    @bot.tree.command(
        name="image",
        description="Generate an image using Google's Nano Banana model"
    )
    @app_commands.checks.cooldown(1, 60)
    @app_commands.describe(
        prompt=(
            "What would you like me to draw?\n"
            "Aspect: --square (default), --wide (16:9), --tall (9:16), "
            "--portrait (3:4), --landscape (4:3), --ultrawide (21:9)\n"
            "Resolution: --1k (default), --2k, --4k"
        )
    )
    async def image_command(interaction: discord.Interaction, prompt: str):
        """Command handler for /image"""
        # Validate prompt length before sending to external API
        if len(prompt) > MAX_PROMPT_LENGTH:
            error_embed = create_embed(
                title="Prompt Too Long",
                description=(
                    f"Your prompt is {len(prompt)} characters. "
                    f"Please keep it under {MAX_PROMPT_LENGTH} characters."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=error_embed, ephemeral=True)
            return
        await bot.generate_image(interaction, prompt)

    @bot.tree.command(name="reset", description="Reset your conversation history with Professor Synapse")
    async def reset_command(interaction: discord.Interaction):
        """Reset user's conversation history."""
        await interaction.response.defer(ephemeral=True)

        try:
            user_id = str(interaction.user.id)
            new_session_uuid = await bot.session_manager.reset_session(user_id)

            await interaction.followup.send(
                "Your conversation has been reset!\n"
                "Starting fresh with a new session.",
                ephemeral=True
            )
            logger.info(f"User {interaction.user.name} ({user_id}) reset their session")

        except Exception as e:
            logger.error(f"Error resetting session: {e}", exc_info=True)
            await interaction.followup.send(
                "Failed to reset conversation history. Please try again later.",
                ephemeral=True
            )

    @bot.tree.command(name="sessioninfo", description="View your session statistics")
    async def sessioninfo_command(interaction: discord.Interaction):
        """Show session information."""
        await interaction.response.defer(ephemeral=True)

        try:
            user_id = str(interaction.user.id)
            info = await bot.session_manager.get_session_info(user_id)

            if info:
                created = datetime.fromisoformat(info['created_at'])
                last_used = datetime.fromisoformat(info['last_used'])

                embed = discord.Embed(
                    title="Your Session Info",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Session ID", value=f"`{info['session_uuid'][:16]}...`", inline=False)
                embed.add_field(name="Created", value=f"<t:{int(created.timestamp())}:R>", inline=True)
                embed.add_field(name="Last Used", value=f"<t:{int(last_used.timestamp())}:R>", inline=True)
                embed.add_field(name="Messages", value=str(info['message_count']), inline=True)

                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send(
                    "You don't have an active session yet. Send a message with `/prof` to start!",
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error getting session info: {e}")
            await interaction.followup.send(
                "Failed to retrieve session info.",
                ephemeral=True
            )

    # Global slash command error handler
    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error: app_commands.AppCommandError
    ):
        """Handle errors raised by slash commands.

        Catches cooldown errors with a user-friendly wait message. All other
        unhandled errors are logged and the user receives a generic error embed
        so they never see 'Application did not respond'.
        """
        if isinstance(error, app_commands.CommandOnCooldown):
            embed = create_embed(
                title="Cooldown Active",
                description=(
                    f"This command is on cooldown. "
                    f"Please try again in **{error.retry_after:.0f}** seconds."
                ),
                color=discord.Color.orange()
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        # Log unexpected errors
        logger.error(
            "Unhandled error in command '%s': %s",
            interaction.command.name if interaction.command else "unknown",
            error,
            exc_info=error,
        )

        error_embed = create_embed(
            title="Error",
            description="An unexpected error occurred while processing your command.",
            color=discord.Color.red()
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=error_embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=error_embed, ephemeral=True)
        except discord.HTTPException:
            # If even the error message fails to send, just log it
            logger.error("Failed to send error response to user")
