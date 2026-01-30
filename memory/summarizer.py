"""
Location: /mnt/f/Code/discordbot/memory/summarizer.py
Summary: Gemini-based reflective summary generation for conversation chunks.
         Produces structured reflections that analyze what happened, key insights,
         and connections to other topics.

Used by: pipeline.py (generates reflections after topic shift detection)
Uses: models.py (ConversationMessage, Reflection)
"""

import asyncio
import json
import logging
from typing import List

from google import genai
from google.genai import types

from memory.models import ConversationMessage, Reflection

logger = logging.getLogger(__name__)


class ConversationSummarizer:
    """Generates AI-powered reflective summaries of conversation chunks.

    Uses Gemini to produce structured analysis including topic identification,
    key insights, and connections to related topics.

    Attributes:
        client: Google Genai client for Gemini API calls.
    """

    MODEL_ID = "gemini-2.0-flash"

    def __init__(self, api_key: str):
        """Initialize the summarizer.

        Args:
            api_key: Google API key for Gemini.
        """
        self.client = genai.Client(api_key=api_key)

    async def generate_reflection(
        self,
        messages: List[ConversationMessage],
        channel_name: str
    ) -> Reflection:
        """Generate a reflective summary of the conversation.

        Analyzes the conversation to extract structured insights including
        topic, key learnings, and connections to other subjects.

        Args:
            messages: List of messages to summarize.
            channel_name: Name of the channel for context.

        Returns:
            Reflection object with structured analysis.
        """
        if not messages:
            return self._empty_reflection()

        conversation_text = self._format_conversation(messages)
        participants = list(set(
            msg.username for msg in messages if not msg.is_bot_response
        ))

        prompt = f"""Analyze this Discord conversation and generate a reflective summary.

CHANNEL: #{channel_name}
PARTICIPANTS: {', '.join(participants) if participants else 'Unknown'}

CONVERSATION:
{conversation_text}

Generate a JSON response with this exact structure:
{{
    "topic": "Brief topic title (3-7 words)",
    "what_happened": "1-3 sentence narrative of what happened in this conversation",
    "key_insights": [
        "First key insight or learning",
        "Second key insight"
    ],
    "about_the_user": [
        "What was learned about the user(s)"
    ],
    "decisions_made": [
        "Any decisions, recommendations, or conclusions reached"
    ],
    "what_went_well": [
        "Positive aspects of the conversation"
    ],
    "what_could_improve": [
        "Areas where the conversation could have been better"
    ],
    "connections": {{
        "related_topics": ["topic1", "topic2"],
        "likely_next_questions": ["What the user might ask next"]
    }},
    "tags": ["tag1", "tag2", "tag3"]
}}

Guidelines:
- Be concise but insightful
- Focus on actionable insights, not just summaries
- Tags should be lowercase, single words or hyphenated phrases
- Leave arrays empty [] if nothing applies (don't invent content)
- The reflection is from the bot's perspective about the conversation"""

        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model=self.MODEL_ID,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.3,  # Balanced creativity and consistency
                    max_output_tokens=1000
                )
            )

            return self._parse_reflection_response(response.text)

        except Exception as e:
            logger.error(f"Failed to generate reflection: {e}")
            # Return a basic reflection on error
            return self._fallback_reflection(messages, participants)

    def _format_conversation(
        self,
        messages: List[ConversationMessage]
    ) -> str:
        """Format messages into readable conversation text.

        Args:
            messages: List of messages to format.

        Returns:
            Formatted conversation string.
        """
        lines = []
        for msg in messages:
            role = "[Bot]" if msg.is_bot_response else f"[{msg.username}]"
            timestamp = msg.timestamp.strftime("%H:%M:%S")
            lines.append(f"[{timestamp}] {role}: {msg.content}")
        return "\n".join(lines)

    def _parse_reflection_response(self, response_text: str) -> Reflection:
        """Parse Gemini's JSON response into a Reflection object.

        Args:
            response_text: Raw response from Gemini.

        Returns:
            Parsed Reflection object.
        """
        # Extract JSON from response (may be wrapped in markdown code blocks)
        json_text = response_text.strip()
        if json_text.startswith('```'):
            # Remove markdown code block
            lines = json_text.split('\n')
            json_lines = []
            in_json = False
            for line in lines:
                if line.strip().startswith('```'):
                    in_json = not in_json
                    continue
                if in_json or not line.strip().startswith('```'):
                    json_lines.append(line)
            json_text = '\n'.join(json_lines)

        try:
            data = json.loads(json_text)
            return Reflection(
                topic=data.get('topic', 'Unknown Topic'),
                what_happened=data.get('what_happened', ''),
                key_insights=data.get('key_insights', []),
                about_the_user=data.get('about_the_user', []),
                decisions_made=data.get('decisions_made', []),
                what_went_well=data.get('what_went_well', []),
                what_could_improve=data.get('what_could_improve', []),
                connections=data.get('connections', {
                    'related_topics': [],
                    'likely_next_questions': []
                }),
                tags=data.get('tags', [])
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse reflection JSON: {e}")
            logger.debug(f"Raw response: {response_text}")
            return self._empty_reflection()

    def _empty_reflection(self) -> Reflection:
        """Create an empty reflection for edge cases.

        Returns:
            Reflection with default/empty values.
        """
        return Reflection(
            topic="Empty Conversation",
            what_happened="No messages to analyze.",
            key_insights=[],
            about_the_user=[],
            decisions_made=[],
            what_went_well=[],
            what_could_improve=[],
            connections={'related_topics': [], 'likely_next_questions': []},
            tags=[]
        )

    def _fallback_reflection(
        self,
        messages: List[ConversationMessage],
        participants: List[str]
    ) -> Reflection:
        """Generate a basic reflection without API call.

        Used as fallback when Gemini API fails.

        Args:
            messages: List of messages.
            participants: List of participant usernames.

        Returns:
            Basic Reflection with available information.
        """
        # Try to infer topic from first user message
        first_user_msg = next(
            (msg for msg in messages if not msg.is_bot_response),
            None
        )
        topic = "General Discussion"
        if first_user_msg and len(first_user_msg.content) > 10:
            # Use first few words as topic
            words = first_user_msg.content.split()[:5]
            topic = ' '.join(words) + '...'

        return Reflection(
            topic=topic,
            what_happened=f"Conversation with {', '.join(participants) if participants else 'users'} "
                         f"containing {len(messages)} messages.",
            key_insights=[],
            about_the_user=[],
            decisions_made=[],
            what_went_well=[],
            what_could_improve=["API error prevented detailed analysis"],
            connections={'related_topics': [], 'likely_next_questions': []},
            tags=[]
        )
