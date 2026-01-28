"""
Image generation module using OpenAI's GPT-Image-1 model.
Provides enums for configuration and a class to handle image generation with flag parsing.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Tuple
import logging
from openai import OpenAI
import json
import base64

# Configure logging
logger = logging.getLogger(__name__)

class ImageSize(Enum):
    """Available image sizes for GPT-Image-1."""
    SQUARE = "1024x1024"
    PORTRAIT = "1536x1024"
    LANDSCAPE = "1024x1536"
    
    @classmethod
    def from_flag(cls, flag: str) -> Optional['ImageSize']:
        """Convert a command flag to ImageSize."""
        flag_map = {
            "--square": cls.SQUARE,
            "--portrait": cls.PORTRAIT,
            "--landscape": cls.LANDSCAPE,
            "--wide": cls.LANDSCAPE
        }
        return flag_map.get(flag.lower())

    @classmethod
    def get_description(cls) -> str:
        """Get help text for size options."""
        return (
            "Size options:\n"
            "  --square: 1024x1024\n"
            "  --portrait: 1536x1024\n"
            "  --landscape: 1024x1536 (or --wide)"
        )

class ImageQuality(Enum):
    """Available quality settings for GPT-Image-1."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    
    @classmethod
    def from_flag(cls, flag: str) -> Optional['ImageQuality']:
        """Convert a command flag to ImageQuality."""
        flag_map = {
            "--low": cls.LOW,
            "--medium": cls.MEDIUM,
            "--high": cls.HIGH
        }
        return flag_map.get(flag.lower())

class ImageFormat(Enum):
    """Available output formats for GPT-Image-1."""
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    
    @classmethod
    def from_flag(cls, flag: str) -> Optional['ImageFormat']:
        """Convert a command flag to ImageFormat."""
        flag_map = {
            "--png": cls.PNG,
            "--jpeg": cls.JPEG,
            "--webp": cls.WEBP
        }
        return flag_map.get(flag.lower())

@dataclass
class ImageConfig:
    """Configuration for image generation."""
    size: ImageSize = ImageSize.SQUARE
    quality: ImageQuality = ImageQuality.MEDIUM
    format: ImageFormat = ImageFormat.PNG

class ImageGenerator:
    """Handles image generation using GPT-Image-1 model."""
    
    def __init__(self, api_key: str):
        """Initialize with OpenAI API key."""
        self.client = OpenAI(api_key=api_key)
    
    def parse_flags(self, prompt: str) -> Tuple[str, ImageConfig]:
        """
        Parse command flags from prompt and return cleaned prompt and config.
        
        Args:
            prompt (str): Raw command input with potential flags
            
        Returns:
            Tuple[str, ImageConfig]: Clean prompt and parsed configuration
        """
        words = prompt.split()
        flags = [w for w in words if w.startswith("--")]
        clean_words = [w for w in words if not w.startswith("--")]
        
        config = ImageConfig()
        
        for flag in flags:
            if size := ImageSize.from_flag(flag):
                config.size = size
            elif quality := ImageQuality.from_flag(flag):
                config.quality = quality
            elif format := ImageFormat.from_flag(flag):
                config.format = format
        
        return " ".join(clean_words), config
    
    async def generate_image(self, prompt: str, config: ImageConfig) -> Tuple[str, bytes]:
        """
        Generate an image using GPT-Image-1.
        
        Args:
            prompt (str): Image description
            config (ImageConfig): Generation configuration
            
        Returns:
            Tuple[str, bytes]: Content type and image data
        """
        try:
            response = self.client.images.generate(
                model="gpt-image-1",
                prompt=prompt,
                size=config.size.value,
                quality=config.quality.value,
                background="auto",
                output_format=config.format.value,
                n=1,
            )
            
            # GPT-Image-1 always returns base64 encoded images
            image_data = base64.b64decode(response.data[0].b64_json)
            content_type = f"image/{config.format.value}"
            
            return content_type, image_data
            
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            raise
