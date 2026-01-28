"""
Tests for DiscordBot._truncate_response static method.

This is a pure function (static method) that truncates text at sentence
boundaries. It has no external dependencies.

Since main.py has heavy import-time side effects (discord, API clients, etc.),
we replicate the function here to test it in isolation. The function body is
copied verbatim from main.py lines 210-246.
"""

import pytest


def _truncate_response(text: str, max_length: int = 4096) -> str:
    """Truncate a response to fit within Discord's embed description limit.

    Attempts to break at the last sentence boundary before the limit.
    Falls back to a hard truncation with an ellipsis indicator if no
    sentence boundary is found.

    Copied from DiscordBot._truncate_response in main.py for isolated testing.
    """
    if len(text) <= max_length:
        return text

    # Reserve space for the truncation indicator
    truncation_indicator = "..."
    limit = max_length - len(truncation_indicator)
    truncated = text[:limit]

    # Try to break at the last sentence-ending punctuation (. ! ?)
    last_sentence_end = max(
        truncated.rfind('. '),
        truncated.rfind('! '),
        truncated.rfind('? '),
        truncated.rfind('.\n'),
        truncated.rfind('!\n'),
        truncated.rfind('?\n'),
    )

    if last_sentence_end > limit // 2:
        # Found a reasonable sentence boundary in the latter half of the text
        truncated = truncated[:last_sentence_end + 1]

    return truncated + truncation_indicator


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTruncateResponse:
    """Tests for the _truncate_response static method."""

    def test_short_text_returned_unchanged(self):
        """Text within the limit should be returned as-is."""
        text = "Hello, world!"
        result = _truncate_response(text, max_length=4096)
        assert result == text

    def test_text_exactly_at_limit(self):
        """Text exactly at the limit should be returned as-is."""
        text = "a" * 4096
        result = _truncate_response(text, max_length=4096)
        assert result == text

    def test_long_text_is_truncated(self):
        """Text exceeding the limit should be truncated with '...' appended."""
        text = "a" * 5000
        result = _truncate_response(text, max_length=100)
        assert len(result) <= 100
        assert result.endswith("...")

    def test_truncation_at_sentence_boundary(self):
        """When possible, truncation should occur at a sentence boundary."""
        # Build a text where a sentence ends roughly in the middle
        sentence1 = "This is the first sentence. "
        sentence2 = "This is the second sentence. "
        # Repeat to exceed the limit
        text = (sentence1 + sentence2) * 20
        result = _truncate_response(text, max_length=100)
        assert result.endswith("...")
        # The text before '...' should end at a sentence boundary (period)
        body = result[:-3]
        assert body.rstrip().endswith(('.', '!', '?'))

    def test_truncation_with_exclamation_boundary(self):
        """Truncation should recognise '!' as a sentence boundary."""
        text = "Wow! " * 50 + "This is extra text that pushes over the limit."
        result = _truncate_response(text, max_length=50)
        assert result.endswith("...")

    def test_truncation_with_question_boundary(self):
        """Truncation should recognise '?' as a sentence boundary."""
        text = "Really? " * 50 + "More text."
        result = _truncate_response(text, max_length=50)
        assert result.endswith("...")

    def test_no_sentence_boundary_falls_back_to_hard_cut(self):
        """Without sentence boundaries, a hard cut should be used."""
        text = "a" * 200  # No sentence-ending punctuation
        result = _truncate_response(text, max_length=100)
        assert result.endswith("...")
        assert len(result) <= 100

    def test_sentence_boundary_too_early_uses_hard_cut(self):
        """If the only sentence boundary is in the first half, use hard cut."""
        # Sentence boundary very early, then a long run of text
        text = "Hi. " + "a" * 200
        result = _truncate_response(text, max_length=100)
        assert result.endswith("...")
        # Should NOT break at "Hi." because it is in the first half of the limit
        assert len(result) <= 100

    def test_custom_max_length(self):
        """The max_length parameter should be respected."""
        text = "a" * 500
        result = _truncate_response(text, max_length=50)
        assert len(result) <= 50
        assert result.endswith("...")

    def test_empty_string(self):
        """An empty string should be returned unchanged."""
        assert _truncate_response("", max_length=4096) == ""

    def test_default_max_length_is_4096(self):
        """The default max_length should be 4096 (Discord embed description limit)."""
        text = "a" * 4096
        result = _truncate_response(text)
        assert result == text  # Exactly at limit, no truncation

        text2 = "a" * 4097
        result2 = _truncate_response(text2)
        assert len(result2) <= 4096
        assert result2.endswith("...")

    def test_sentence_boundary_with_newline(self):
        """Sentence boundaries followed by newlines should be recognised."""
        text = "First sentence.\nSecond sentence.\n" + "a" * 200
        result = _truncate_response(text, max_length=60)
        assert result.endswith("...")

    def test_result_never_exceeds_max_length(self):
        """The result should never exceed max_length regardless of input."""
        for length in [10, 50, 100, 500, 4096]:
            text = "Hello world. This is a test! Is it working? " * 100
            result = _truncate_response(text, max_length=length)
            assert len(result) <= length, (
                f"Result length {len(result)} exceeds max_length {length}"
            )

    def test_truncation_preserves_sentence_end_character(self):
        """The sentence-ending character should be preserved in the output."""
        # Place a clear sentence boundary in the latter half
        text = "a" * 40 + "End here. " + "b" * 60
        result = _truncate_response(text, max_length=60)
        assert result.endswith("...")
        body = result[:-3]
        # The body should end with the period from "End here."
        assert body.endswith(".")

    def test_one_character_over_limit(self):
        """Text that is exactly one character over the limit should be truncated."""
        text = "a" * 4097
        result = _truncate_response(text, max_length=4096)
        assert len(result) <= 4096
        assert result.endswith("...")
