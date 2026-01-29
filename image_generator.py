"""
Image generation module using Google's Nano Banana model (gemini-2.5-flash-image).

Location: /mnt/f/Code/discordbot/image_generator.py
Summary: Provides enums for aspect ratio and resolution configuration, flag parsing from
         user prompts, and async image generation via the Gemini API. Used by main.py's
         /image slash command to produce AI-generated images in Discord.
"""

import asyncio
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Tuple
import logging
from google import genai
from google.genai import types

# Configure logging
logger = logging.getLogger(__name__)


class AspectRatio(Enum):
    """
    Available aspect ratios for Nano Banana image generation.

    Each member maps to a ratio string accepted by the Gemini API and one or more
    user-facing command flags.
    """
    SQUARE = "1:1"
    PORTRAIT_2_3 = "2:3"
    LANDSCAPE_3_2 = "3:2"
    PORTRAIT_3_4 = "3:4"
    LANDSCAPE_4_3 = "4:3"
    PORTRAIT_4_5 = "4:5"
    LANDSCAPE_5_4 = "5:4"
    TALL = "9:16"
    WIDE = "16:9"
    ULTRAWIDE = "21:9"

    @classmethod
    def from_flag(cls, flag: str) -> Optional['AspectRatio']:
        """Convert a command flag to an AspectRatio.

        Args:
            flag: A user-supplied flag string (e.g. '--wide').

        Returns:
            The matching AspectRatio member, or None if the flag is not recognised.
        """
        flag_map = {
            "--square": cls.SQUARE,
            "--1:1": cls.SQUARE,
            "--portrait": cls.PORTRAIT_3_4,
            "--3:4": cls.PORTRAIT_3_4,
            "--landscape": cls.LANDSCAPE_4_3,
            "--4:3": cls.LANDSCAPE_4_3,
            "--tall": cls.TALL,
            "--9:16": cls.TALL,
            "--wide": cls.WIDE,
            "--16:9": cls.WIDE,
            "--ultrawide": cls.ULTRAWIDE,
            "--21:9": cls.ULTRAWIDE,
            "--2:3": cls.PORTRAIT_2_3,
            "--3:2": cls.LANDSCAPE_3_2,
            "--4:5": cls.PORTRAIT_4_5,
            "--5:4": cls.LANDSCAPE_5_4,
        }
        return flag_map.get(flag.lower())

    @classmethod
    def get_description(cls) -> str:
        """Get help text describing the available aspect ratio flags."""
        return (
            "Aspect ratio options:\n"
            "  --square (default, 1:1)\n"
            "  --wide (16:9)\n"
            "  --tall (9:16)\n"
            "  --portrait (3:4)\n"
            "  --landscape (4:3)\n"
            "  --ultrawide (21:9)\n"
            "  Also: --2:3, --3:2, --4:5, --5:4"
        )


class Resolution(Enum):
    """
    Available output resolutions for Nano Banana image generation.

    Note: The gemini-2.5-flash-image model does NOT currently support the image_size
    parameter. This enum is retained for future use or alternative models. Resolution
    flags are parsed but not passed to the API.
    """
    ONE_K = "1K"
    TWO_K = "2K"
    FOUR_K = "4K"

    @classmethod
    def from_flag(cls, flag: str) -> Optional['Resolution']:
        """Convert a command flag to a Resolution.

        Args:
            flag: A user-supplied flag string (e.g. '--2k').

        Returns:
            The matching Resolution member, or None if the flag is not recognised.
        """
        flag_map = {
            "--1k": cls.ONE_K,
            "--2k": cls.TWO_K,
            "--4k": cls.FOUR_K,
        }
        return flag_map.get(flag.lower())

    @classmethod
    def get_description(cls) -> str:
        """Get help text describing the available resolution flags."""
        return (
            "Resolution options:\n"
            "  --1k (default)\n"
            "  --2k\n"
            "  --4k"
        )


@dataclass
class ImageConfig:
    """Configuration for a single image generation request.

    Attributes:
        aspect_ratio: The desired aspect ratio (default square 1:1).
        resolution: The desired output resolution (default 1K). Note: Currently not
            passed to the API as gemini-2.5-flash-image does not support image_size.
    """
    aspect_ratio: AspectRatio = AspectRatio.SQUARE
    resolution: Resolution = Resolution.ONE_K


class ImageGenerator:
    """Handles image generation using Google's Nano Banana model (gemini-2.5-flash-image).

    Usage:
        generator = ImageGenerator(api_key="YOUR_KEY")
        clean_prompt, config = generator.parse_flags("a cat --wide --2k")
        content_type, image_bytes = await generator.generate_image(clean_prompt, config)
    """

    # The single model identifier for Nano Banana.
    MODEL_ID = "gemini-2.5-flash-image"

    def __init__(self, api_key: str):
        """Initialise the generator with a Google API key.

        Args:
            api_key: Google API key that has access to the Gemini API.
        """
        self.client = genai.Client(api_key=api_key)

    def parse_flags(self, prompt: str) -> Tuple[str, ImageConfig]:
        """Parse command flags from the user prompt and return the cleaned prompt with config.

        Flags are words beginning with '--'. Recognised flags are consumed into the
        returned ImageConfig; unrecognised flags are silently stripped so they do not
        pollute the generation prompt.

        Args:
            prompt: Raw user input which may contain flags interspersed with the
                    image description.

        Returns:
            A tuple of (cleaned_prompt, ImageConfig) where cleaned_prompt has all
            flag tokens removed.
        """
        words = prompt.split()
        flags = [w for w in words if w.startswith("--")]
        clean_words = [w for w in words if not w.startswith("--")]

        config = ImageConfig()

        for flag in flags:
            if aspect := AspectRatio.from_flag(flag):
                config.aspect_ratio = aspect
            elif resolution := Resolution.from_flag(flag):
                config.resolution = resolution
            # Unrecognised flags are intentionally ignored.

        return " ".join(clean_words), config

    async def generate_image(self, prompt: str, config: ImageConfig) -> Tuple[str, bytes]:
        """Generate an image via the Nano Banana model.

        The Gemini generate_content call is synchronous within the google-genai SDK,
        so it is offloaded to a thread pool via asyncio.to_thread() to avoid blocking
        the event loop.

        Note: The gemini-2.5-flash-image model only supports aspect_ratio in ImageConfig.
        The image_size parameter is NOT supported by this model (it would cause a 400
        INVALID_ARGUMENT error). Resolution flags are parsed but currently ignored.

        Args:
            prompt: The image description (flags already stripped).
            config: Generation settings (aspect ratio and resolution).

        Returns:
            A tuple of (mime_type, image_bytes). The mime_type will typically be
            'image/png' as determined by the API.

        Raises:
            ValueError: If the API response does not contain image data.
            Exception: Propagates any API or network errors after logging.
        """
        # Note: Resolution flags are parsed but not passed to the API.
        # gemini-2.5-flash-image does not support image_size parameter.
        if config.resolution != Resolution.ONE_K:
            logger.info(
                "Resolution flag %s parsed but ignored; "
                "gemini-2.5-flash-image does not support image_size parameter",
                config.resolution.value,
            )

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.MODEL_ID,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                    image_config=types.ImageConfig(
                        aspect_ratio=config.aspect_ratio.value,
                    ),
                ),
            )

            logger.info(
                "Generated image using %s, aspect_ratio=%s",
                self.MODEL_ID,
                config.aspect_ratio.value,
            )

            # Extract the first image part from the response.
            for part in response.parts:
                if part.inline_data is not None:
                    content_type = part.inline_data.mime_type
                    image_data = part.inline_data.data
                    return content_type, image_data

            # If we reach here, the response contained no image data.
            raise ValueError(
                "Nano Banana response did not contain image data. "
                "The model may have refused the prompt or returned text only."
            )

        except Exception as e:
            logger.error("Image generation failed: %s", e)
            raise
