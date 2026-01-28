"""
Tests for image_generator.py -- AspectRatio.from_flag, Resolution.from_flag,
and ImageGenerator.parse_flags.

These are pure functions with no external dependencies beyond the module itself.
"""

import pytest
from unittest.mock import MagicMock, patch

# Patch genai before importing ImageGenerator so it does not try to contact Google.
with patch.dict("sys.modules", {"google": MagicMock(), "google.genai": MagicMock(), "google.genai.types": MagicMock()}):
    from image_generator import AspectRatio, Resolution, ImageConfig, ImageGenerator


# ---------------------------------------------------------------------------
# AspectRatio.from_flag
# ---------------------------------------------------------------------------

class TestAspectRatioFromFlag:
    """Tests for AspectRatio.from_flag class method."""

    @pytest.mark.parametrize(
        "flag, expected",
        [
            ("--square", AspectRatio.SQUARE),
            ("--1:1", AspectRatio.SQUARE),
            ("--portrait", AspectRatio.PORTRAIT_3_4),
            ("--3:4", AspectRatio.PORTRAIT_3_4),
            ("--landscape", AspectRatio.LANDSCAPE_4_3),
            ("--4:3", AspectRatio.LANDSCAPE_4_3),
            ("--tall", AspectRatio.TALL),
            ("--9:16", AspectRatio.TALL),
            ("--wide", AspectRatio.WIDE),
            ("--16:9", AspectRatio.WIDE),
            ("--ultrawide", AspectRatio.ULTRAWIDE),
            ("--21:9", AspectRatio.ULTRAWIDE),
            ("--2:3", AspectRatio.PORTRAIT_2_3),
            ("--3:2", AspectRatio.LANDSCAPE_3_2),
            ("--4:5", AspectRatio.PORTRAIT_4_5),
            ("--5:4", AspectRatio.LANDSCAPE_5_4),
        ],
    )
    def test_recognised_flags(self, flag, expected):
        """Each known flag should return the correct AspectRatio member."""
        assert AspectRatio.from_flag(flag) is expected

    def test_case_insensitive(self):
        """Flags should be matched case-insensitively."""
        assert AspectRatio.from_flag("--WIDE") is AspectRatio.WIDE
        assert AspectRatio.from_flag("--Wide") is AspectRatio.WIDE
        assert AspectRatio.from_flag("--TALL") is AspectRatio.TALL

    def test_unrecognised_flag_returns_none(self):
        """An unknown flag should return None, not raise."""
        assert AspectRatio.from_flag("--banana") is None

    def test_empty_flag_returns_none(self):
        """An empty string (with --) should return None."""
        assert AspectRatio.from_flag("--") is None

    def test_flag_without_dashes_returns_none(self):
        """A flag without the '--' prefix should return None."""
        assert AspectRatio.from_flag("wide") is None


# ---------------------------------------------------------------------------
# Resolution.from_flag
# ---------------------------------------------------------------------------

class TestResolutionFromFlag:
    """Tests for Resolution.from_flag class method."""

    @pytest.mark.parametrize(
        "flag, expected",
        [
            ("--1k", Resolution.ONE_K),
            ("--2k", Resolution.TWO_K),
            ("--4k", Resolution.FOUR_K),
        ],
    )
    def test_recognised_flags(self, flag, expected):
        """Each known resolution flag should return the correct member."""
        assert Resolution.from_flag(flag) is expected

    def test_case_insensitive(self):
        """Resolution flags should be matched case-insensitively."""
        assert Resolution.from_flag("--2K") is Resolution.TWO_K
        assert Resolution.from_flag("--4K") is Resolution.FOUR_K

    def test_unrecognised_flag_returns_none(self):
        """An unknown resolution flag should return None."""
        assert Resolution.from_flag("--8k") is None
        assert Resolution.from_flag("--hd") is None


# ---------------------------------------------------------------------------
# ImageGenerator.parse_flags
# ---------------------------------------------------------------------------

class TestParseFlags:
    """Tests for ImageGenerator.parse_flags."""

    @pytest.fixture
    def generator(self):
        """Create an ImageGenerator with a mocked client."""
        with patch("image_generator.genai"):
            gen = ImageGenerator.__new__(ImageGenerator)
            gen.client = MagicMock()
            return gen

    def test_no_flags(self, generator):
        """A prompt with no flags should return the original text and default config."""
        clean, config = generator.parse_flags("a beautiful sunset over the ocean")
        assert clean == "a beautiful sunset over the ocean"
        assert config.aspect_ratio is AspectRatio.SQUARE
        assert config.resolution is Resolution.ONE_K

    def test_single_aspect_flag(self, generator):
        """A single aspect ratio flag should be parsed correctly."""
        clean, config = generator.parse_flags("a cat --wide")
        assert clean == "a cat"
        assert config.aspect_ratio is AspectRatio.WIDE
        assert config.resolution is Resolution.ONE_K

    def test_single_resolution_flag(self, generator):
        """A single resolution flag should be parsed correctly."""
        clean, config = generator.parse_flags("a dog --2k")
        assert clean == "a dog"
        assert config.resolution is Resolution.TWO_K
        assert config.aspect_ratio is AspectRatio.SQUARE

    def test_both_flags(self, generator):
        """Both aspect ratio and resolution flags should be parsed."""
        clean, config = generator.parse_flags("a cat --wide --2k")
        assert clean == "a cat"
        assert config.aspect_ratio is AspectRatio.WIDE
        assert config.resolution is Resolution.TWO_K

    def test_flags_in_middle_of_prompt(self, generator):
        """Flags can appear anywhere in the prompt."""
        clean, config = generator.parse_flags("a --tall cat sitting on a fence")
        assert clean == "a cat sitting on a fence"
        assert config.aspect_ratio is AspectRatio.TALL

    def test_unrecognised_flags_are_stripped(self, generator):
        """Unrecognised flags should be stripped from the clean prompt."""
        clean, config = generator.parse_flags("a cat --unknown --wide on a roof")
        assert clean == "a cat on a roof"
        assert config.aspect_ratio is AspectRatio.WIDE

    def test_empty_prompt(self, generator):
        """An empty prompt should return an empty clean prompt and default config."""
        clean, config = generator.parse_flags("")
        assert clean == ""
        assert config.aspect_ratio is AspectRatio.SQUARE
        assert config.resolution is Resolution.ONE_K

    def test_only_flags(self, generator):
        """A prompt with only flags should return an empty clean prompt."""
        clean, config = generator.parse_flags("--wide --4k")
        assert clean == ""
        assert config.aspect_ratio is AspectRatio.WIDE
        assert config.resolution is Resolution.FOUR_K

    def test_last_aspect_flag_wins(self, generator):
        """When multiple aspect ratio flags are given, the last one should win."""
        clean, config = generator.parse_flags("a cat --wide --tall")
        assert clean == "a cat"
        assert config.aspect_ratio is AspectRatio.TALL

    def test_last_resolution_flag_wins(self, generator):
        """When multiple resolution flags are given, the last one should win."""
        clean, config = generator.parse_flags("a cat --2k --4k")
        assert clean == "a cat"
        assert config.resolution is Resolution.FOUR_K

    def test_extra_whitespace_is_normalised(self, generator):
        """Extra whitespace in the prompt should be normalised by split/join."""
        clean, config = generator.parse_flags("a   cat   --wide   on   a   roof")
        assert clean == "a cat on a roof"
        assert config.aspect_ratio is AspectRatio.WIDE

    def test_case_insensitive_flags(self, generator):
        """Flags should be case-insensitive in parse_flags."""
        clean, config = generator.parse_flags("a cat --WIDE --2K")
        assert clean == "a cat"
        assert config.aspect_ratio is AspectRatio.WIDE
        assert config.resolution is Resolution.TWO_K

    def test_numeric_ratio_flags(self, generator):
        """Numeric ratio flags like --16:9 should work."""
        clean, config = generator.parse_flags("sunset --16:9 --4k")
        assert clean == "sunset"
        assert config.aspect_ratio is AspectRatio.WIDE
        assert config.resolution is Resolution.FOUR_K
