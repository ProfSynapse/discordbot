"""
Location: /mnt/f/Code/discordbot/gallery.py
Summary: Gallery posting functionality for the Discord bot.
         Handles posting generated images to a forum channel for community viewing.
         Separated from main.py to reduce file size and improve modularity.

Used by: main.py calls post_to_gallery() from the generate_image command handler.
Uses: config.py (IMAGE_GALLERY_CHANNEL_ID).
"""

import io
import logging

import discord

from config import config

logger = logging.getLogger(__name__)


async def post_to_gallery(
    bot,
    image_data: bytes,
    prompt: str,
    user: discord.User,
    aspect_ratio: str
) -> None:
    """Post a generated image to the gallery forum channel.

    Creates a new forum post/thread with the image attached. The thread title
    is the prompt (truncated to 100 chars per Discord's limit), and the initial
    message includes an embed with full details.

    This is a fire-and-forget helper that logs errors but never raises them,
    so failures do not affect the user's primary response.

    Args:
        bot: The DiscordBot instance (needed for channel fetching).
        image_data: The raw PNG image bytes.
        prompt: The cleaned prompt used for generation.
        user: The Discord user who requested the image.
        aspect_ratio: The aspect ratio string (e.g., "16:9").
    """
    if not config.IMAGE_GALLERY_CHANNEL_ID:
        logger.info("IMAGE_GALLERY_CHANNEL_ID not configured; skipping gallery post")
        return

    logger.info("Attempting to post to gallery channel %s", config.IMAGE_GALLERY_CHANNEL_ID)

    try:
        gallery_channel = bot.get_channel(config.IMAGE_GALLERY_CHANNEL_ID)
        if gallery_channel is None:
            # Channel not in cache; try fetching it
            gallery_channel = await bot.fetch_channel(config.IMAGE_GALLERY_CHANNEL_ID)

        if gallery_channel is None:
            logger.warning(
                "Gallery channel %s not found; skipping gallery post",
                config.IMAGE_GALLERY_CHANNEL_ID
            )
            return

        # Verify it's a forum channel
        if not isinstance(gallery_channel, discord.ForumChannel):
            logger.warning(
                "Gallery channel %s is not a ForumChannel (got %s); skipping gallery post",
                config.IMAGE_GALLERY_CHANNEL_ID,
                type(gallery_channel).__name__
            )
            return

        # Create an embed for the gallery post
        embed = discord.Embed(
            description=f"*{prompt}*",
            color=discord.Color.purple()
        )
        embed.set_image(url="attachment://gallery_image.png")
        embed.add_field(name="Requested by", value=user.mention, inline=True)
        embed.add_field(name="Aspect Ratio", value=aspect_ratio, inline=True)
        embed.set_footer(text="Generated with /image command")

        # Create a new file object for the gallery (can't reuse the original)
        gallery_file = discord.File(
            fp=io.BytesIO(image_data),
            filename="gallery_image.png"
        )

        # Truncate prompt to 100 chars for thread title (Discord limit)
        thread_title = prompt[:97] + "..." if len(prompt) > 100 else prompt

        # Create a forum post (thread) with the image
        # Note: ForumChannel.create_thread requires content even though docs say optional
        # See: https://github.com/Rapptz/discord.py/discussions/9185
        await gallery_channel.create_thread(
            name=thread_title,
            content=prompt,
            embed=embed,
            file=gallery_file
        )
        logger.info(
            "Posted image to gallery forum %s (requested by %s)",
            config.IMAGE_GALLERY_CHANNEL_ID,
            user.name
        )

    except discord.Forbidden:
        logger.warning(
            "Bot lacks permission to post to gallery channel %s",
            config.IMAGE_GALLERY_CHANNEL_ID
        )
    except discord.HTTPException as e:
        logger.error(
            "HTTP error posting to gallery channel %s: %s",
            config.IMAGE_GALLERY_CHANNEL_ID,
            e
        )
    except Exception as e:
        logger.error(
            "Unexpected error posting to gallery channel %s: %s",
            config.IMAGE_GALLERY_CHANNEL_ID,
            e,
            exc_info=True
        )
