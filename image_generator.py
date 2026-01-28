"""
Image generation module using Google's Imagen 4 models.
Provides enums for configuration and a class to handle image generation with flag parsing.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Tuple
import logging
from google import genai
from google.genai.types import GenerateImagesConfig
import io

# Configure logging
logger = logging.getLogger(__name__)

class ImageModel(Enum):
    """Available Imagen 4 model variants."""
    FAST = "imagen-4.0-fast-generate-001"  # Fastest generation, good quality
    STANDARD = "imagen-4.0-generate-001"   # Balanced speed and quality
    ULTRA = "imagen-4.0-ultra-generate-001"  # Highest quality, slower
    
    @classmethod
    def from_flag(cls, flag: str) -> Optional['ImageModel']:
        """Convert a command flag to ImageModel."""
        flag_map = {
            "--fast": cls.FAST,
            "--standard": cls.STANDARD,
            "--ultra": cls.ULTRA
        }
        return flag_map.get(flag.lower())
    
    @classmethod
    def get_description(cls) -> str:
        """Get help text for model options."""
        return (
            "Model options:\n"
            "  --fast: Quick generation (default)\n"
            "  --standard: Balanced quality\n"
            "  --ultra: Premium quality"
        )

class ImageSize(Enum):
    """
    Available image sizes for Imagen 4.
    
    Note: Only Standard and Ultra models support size selection (1K or 2K).
    Fast model uses a fixed default size and does not accept size parameters.
    """
    SQUARE_1K = "1K"  # 1024x1024 (default)
    SQUARE_2K = "2K"  # 2048x2048
    
    @classmethod
    def from_flag(cls, flag: str) -> Optional['ImageSize']:
        """Convert a command flag to ImageSize."""
        flag_map = {
            "--square": cls.SQUARE_1K,  # Default square 1K
            "--1k": cls.SQUARE_1K,
            "--square-1k": cls.SQUARE_1K,
            "--2k": cls.SQUARE_2K,
            "--square-2k": cls.SQUARE_2K,
            "--large": cls.SQUARE_2K,  # Alias for 2K
        }
        return flag_map.get(flag.lower())

    @classmethod
    def get_description(cls) -> str:
        """Get help text for size options."""
        return (
            "Size options (Standard/Ultra models only):\n"
            "  --square or --1k: 1024x1024 (default)\n"
            "  --2k or --large: 2048x2048\n"
            "Note: Fast model uses fixed default size"
        )

class ImageFormat(Enum):
    """Available output formats for Imagen 4."""
    PNG = "png"
    JPEG = "jpeg"
    
    @classmethod
    def from_flag(cls, flag: str) -> Optional['ImageFormat']:
        """Convert a command flag to ImageFormat."""
        flag_map = {
            "--png": cls.PNG,
            "--jpeg": cls.JPEG,
            "--jpg": cls.JPEG
        }
        return flag_map.get(flag.lower())

@dataclass
class ImageConfig:
    """Configuration for image generation."""
    model: ImageModel = ImageModel.FAST  # Default to fast model
    size: ImageSize = ImageSize.SQUARE_1K
    format: ImageFormat = ImageFormat.PNG

class ImageGenerator:
    """Handles image generation using Google's Imagen 4 models."""
    
    def __init__(self, api_key: str):
        """
        Initialize with Google API credentials.
        
        Args:
            api_key: Google API key for Vertex AI
        """
        self.client = genai.Client(api_key=api_key)
    
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
            if model := ImageModel.from_flag(flag):
                config.model = model
            elif size := ImageSize.from_flag(flag):
                config.size = size
            elif format := ImageFormat.from_flag(flag):
                config.format = format
        
        return " ".join(clean_words), config
    
    async def generate_image(self, prompt: str, config: ImageConfig) -> Tuple[str, bytes]:
        """
        Generate an image using Google's Imagen 4.
        
        Args:
            prompt (str): Image description
            config (ImageConfig): Generation configuration
            
        Returns:
            Tuple[str, bytes]: Content type and image data
        """
        try:
            # Fast model doesn't support size parameter - use defaults only
            if config.model == ImageModel.FAST:
                response = self.client.models.generate_images(
                    model=config.model.value,
                    prompt=prompt,
                    config=GenerateImagesConfig(
                        output_mime_type=f"image/{config.format.value}"
                    )
                )
                logger.info(f"Generated image using {config.model.value} (default size)")
            else:
                # Standard and Ultra models support 1K or 2K sizes
                response = self.client.models.generate_images(
                    model=config.model.value,
                    prompt=prompt,
                    config=GenerateImagesConfig(
                        image_size=config.size.value,
                        output_mime_type=f"image/{config.format.value}"
                    )
                )
                logger.info(f"Generated image using {config.model.value}, size: {config.size.value}")
            
            # Extract image bytes from response
            image_data = response.generated_images[0].image.image_bytes
            content_type = f"image/{config.format.value}"
            
            return content_type, image_data
            
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            raise
