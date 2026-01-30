"""
Location: /mnt/f/Code/discordbot/memory/detector.py
Summary: Topic shift detection using a hybrid approach: simple heuristics (time gaps)
         combined with Gemini API for detecting subtle semantic shifts. The heuristics
         handle obvious cases (30+ minute gaps), while Gemini handles nuanced shifts.

Used by: pipeline.py (checks for topic shifts during background processing)
Uses: models.py (ConversationMessage, TopicShiftResult)
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from google import genai
from google.genai import types

from memory.models import ConversationMessage, TopicShiftResult

logger = logging.getLogger(__name__)


class TopicDetector:
    """Detects topic shifts in conversations using heuristics and Gemini API.

    The detection strategy is layered:
    1. Time-based heuristics (fast, no API cost) - gaps > 30 min = shift
    2. Gemini semantic analysis (slower, API cost) - for subtle shifts

    Attributes:
        client: Google Genai client for Gemini API calls.
        time_gap_threshold: Seconds of inactivity that triggers automatic shift.
        min_messages_for_detection: Minimum messages needed before detection runs.
    """

    # Gemini model for text analysis (same family as image model)
    MODEL_ID = "gemini-2.0-flash"

    def __init__(
        self,
        api_key: str,
        time_gap_threshold: int = 1800,  # 30 minutes
        min_messages_for_detection: int = 4
    ):
        """Initialize the topic detector.

        Args:
            api_key: Google API key for Gemini.
            time_gap_threshold: Seconds of inactivity that triggers automatic shift.
            min_messages_for_detection: Minimum messages before detection runs.
        """
        self.client = genai.Client(api_key=api_key)
        self.time_gap_threshold = time_gap_threshold
        self.min_messages_for_detection = min_messages_for_detection

    async def detect_shift(
        self,
        messages: List[ConversationMessage]
    ) -> TopicShiftResult:
        """Detect whether a topic shift has occurred in the conversation.

        Uses a layered approach:
        1. Not enough messages -> no shift
        2. Time gap detected -> automatic shift
        3. Gemini analysis -> semantic shift detection

        Args:
            messages: List of recent messages to analyze.

        Returns:
            TopicShiftResult indicating if/why a shift occurred.
        """
        if len(messages) < self.min_messages_for_detection:
            return TopicShiftResult(
                is_shift=False,
                confidence=1.0,
                reason=f"Insufficient messages ({len(messages)} < {self.min_messages_for_detection})"
            )

        # Check for time gap between last two messages
        time_shift = self._check_time_gap(messages)
        if time_shift.is_shift:
            return time_shift

        # Use Gemini for semantic analysis
        try:
            return await self._analyze_with_gemini(messages)
        except Exception as e:
            # Log at WARNING level since this affects detection reliability
            logger.warning(f"Gemini topic detection failed: {e}")
            # Fail open - don't trigger a shift on API errors.
            # Use api_error flag to distinguish from genuine "no shift" detection.
            return TopicShiftResult(
                is_shift=False,
                confidence=0.0,
                reason=f"API error: {e}",
                api_error=True  # Indicates detection was not completed
            )

    def _check_time_gap(
        self,
        messages: List[ConversationMessage]
    ) -> TopicShiftResult:
        """Check for a significant time gap between recent messages.

        A gap larger than time_gap_threshold seconds between any two
        consecutive messages indicates a natural conversation break.

        Args:
            messages: List of messages to check.

        Returns:
            TopicShiftResult (is_shift=True if gap detected).
        """
        if len(messages) < 2:
            return TopicShiftResult(
                is_shift=False,
                confidence=1.0,
                reason="Not enough messages to check time gap"
            )

        for i in range(1, len(messages)):
            prev_msg = messages[i - 1]
            curr_msg = messages[i]

            # Handle timezone-naive datetimes
            prev_time = prev_msg.timestamp
            curr_time = curr_msg.timestamp

            if prev_time.tzinfo is None:
                prev_time = prev_time.replace(tzinfo=timezone.utc)
            if curr_time.tzinfo is None:
                curr_time = curr_time.replace(tzinfo=timezone.utc)

            gap_seconds = (curr_time - prev_time).total_seconds()

            if gap_seconds > self.time_gap_threshold:
                logger.info(
                    f"Time gap detected: {gap_seconds:.0f}s > {self.time_gap_threshold}s"
                )
                return TopicShiftResult(
                    is_shift=True,
                    confidence=1.0,
                    reason=f"Time gap of {gap_seconds:.0f} seconds detected"
                )

        return TopicShiftResult(
            is_shift=False,
            confidence=1.0,
            reason="No significant time gap"
        )

    async def _analyze_with_gemini(
        self,
        messages: List[ConversationMessage]
    ) -> TopicShiftResult:
        """Use Gemini to detect semantic topic shifts.

        Sends the recent conversation to Gemini with a prompt asking it
        to identify if the topic has shifted meaningfully.

        Args:
            messages: List of messages to analyze.

        Returns:
            TopicShiftResult based on Gemini's analysis.
        """
        # Format conversation for analysis
        conversation_text = self._format_conversation(messages)

        prompt = f"""Analyze this conversation and determine if there's a meaningful topic shift.

CONVERSATION:
{conversation_text}

INSTRUCTIONS:
1. Look for changes in the subject matter, not just natural conversation flow
2. Minor clarifications or follow-ups on the same topic are NOT shifts
3. A shift means the conversation has moved to a distinctly different subject

Respond in this exact format:
SHIFT: [YES or NO]
CONFIDENCE: [0.0 to 1.0]
TOPIC: [Brief description of current topic if YES, otherwise "same topic"]
REASON: [One sentence explanation]

Example responses:
SHIFT: YES
CONFIDENCE: 0.85
TOPIC: Python debugging techniques
REASON: Conversation moved from general project setup to specific debugging strategies.

SHIFT: NO
CONFIDENCE: 0.95
TOPIC: same topic
REASON: User is asking follow-up questions about the same subject."""

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.MODEL_ID,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,  # Low temperature for consistent analysis
                    max_output_tokens=200
                )
            )

            # Parse the response
            result_text = response.text.strip()
            return self._parse_gemini_response(result_text)

        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise

    def _format_conversation(
        self,
        messages: List[ConversationMessage]
    ) -> str:
        """Format messages into a readable conversation string.

        Args:
            messages: List of messages to format.

        Returns:
            Formatted string with timestamps and authors.
        """
        lines = []
        for msg in messages:
            role = "[BOT]" if msg.is_bot_response else f"[{msg.username}]"
            timestamp = msg.timestamp.strftime("%H:%M")
            lines.append(f"{timestamp} {role}: {msg.content}")
        return "\n".join(lines)

    def _parse_gemini_response(self, response_text: str) -> TopicShiftResult:
        """Parse Gemini's structured response into TopicShiftResult.

        Args:
            response_text: Raw text response from Gemini.

        Returns:
            Parsed TopicShiftResult.
        """
        lines = response_text.strip().split('\n')

        is_shift = False
        confidence = 0.5
        topic = None
        reason = None

        for line in lines:
            line = line.strip()
            if line.upper().startswith('SHIFT:'):
                value = line.split(':', 1)[1].strip().upper()
                is_shift = value == 'YES'
            elif line.upper().startswith('CONFIDENCE:'):
                try:
                    confidence = float(line.split(':', 1)[1].strip())
                except ValueError:
                    confidence = 0.5
            elif line.upper().startswith('TOPIC:'):
                topic = line.split(':', 1)[1].strip()
                if topic.lower() == 'same topic':
                    topic = None
            elif line.upper().startswith('REASON:'):
                reason = line.split(':', 1)[1].strip()

        return TopicShiftResult(
            is_shift=is_shift,
            confidence=confidence,
            topic_summary=topic,
            reason=reason
        )

    def should_force_chunk(
        self,
        messages: List[ConversationMessage],
        max_time_without_chunk: int = 1800  # 30 minutes
    ) -> bool:
        """Check if we should force a chunk due to time/size constraints.

        Forces chunking when:
        - Buffer has been accumulating for too long without a topic shift
        - Buffer is getting very large

        Args:
            messages: Current buffer messages.
            max_time_without_chunk: Max seconds before forcing a chunk.

        Returns:
            True if a chunk should be forced.
        """
        if not messages:
            return False

        # Force if buffer is very large
        if len(messages) >= 50:
            logger.info("Forcing chunk due to buffer size (50+ messages)")
            return True

        # Force if oldest message is too old
        oldest = messages[0].timestamp
        if oldest.tzinfo is None:
            oldest = oldest.replace(tzinfo=timezone.utc)

        age_seconds = (datetime.now(timezone.utc) - oldest).total_seconds()
        if age_seconds > max_time_without_chunk:
            logger.info(
                f"Forcing chunk due to age ({age_seconds:.0f}s > {max_time_without_chunk}s)"
            )
            return True

        return False
