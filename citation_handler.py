"""
Location: /mnt/f/Code/discordbot/citation_handler.py
Summary: Processes GPT Trainer citation data and transforms response text.

    When ``show_citations`` is enabled on the GPT Trainer chatbot, the AI
    embeds ``[X.Y]`` markers in its response text and the message object
    carries a ``cite_data_json`` field mapping those markers to source
    metadata (title, file name, type, chunk text, etc.).

    This module:
    - Parses ``cite_data_json`` from the most recent assistant message
    - For **URL-type** sources: collects unique source links and appends
      a "Sources" footer with markdown hyperlinks
    - For **upload/file-type** sources: strips the ``[X.Y]`` markers from
      the response text entirely (no useful link to show the user)
    - Passes text through unchanged when no citation data is present

Used by: main.py (``/prof`` command and ``on_message`` handler)
"""

import json
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Matches citation markers like [1.2], [23.4], [3.10]
_CITATION_PATTERN = re.compile(r'\[(\d+(?:\.\d+)?)\]')


def extract_cite_data(messages: list) -> Optional[Dict]:
    """Extract ``cite_data_json`` from the most recent assistant message.

    GPT Trainer returns messages in chronological order. The last message
    in the list is the most recent assistant response, which is the one
    carrying citation data.

    Args:
        messages: List of message dicts returned by
                  ``GPTTrainerAPI.fetch_session_messages()``.

    Returns:
        Parsed citation data dict, or ``None`` if unavailable.
    """
    if not messages:
        return None

    # The most recent message should be the assistant's response.
    # Walk backwards to find the first message with cite_data_json.
    for msg in reversed(messages):
        raw = msg.get('cite_data_json')
        if not raw:
            continue

        # cite_data_json may already be a dict (if the API pre-parsed it)
        # or a JSON string that needs parsing.
        if isinstance(raw, dict):
            return raw if raw else None

        if isinstance(raw, str):
            raw = raw.strip()
            if not raw or raw in ('{}', 'null', '""'):
                continue
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and parsed:
                    return parsed
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning("Failed to parse cite_data_json: %s", exc)

    return None


def process_citations(response_text: str, cite_data: Optional[Dict]) -> str:
    """Process citation markers in ``response_text`` using ``cite_data``.

    Behavior per source type:
    - **url** (web sources): The ``[X.Y]`` marker is stripped from the
      inline text and a deduplicated "Sources" footer is appended with
      markdown links.
    - **upload** / **file** / anything else: The ``[X.Y]`` marker is
      simply stripped from the text. No link to show.

    If ``cite_data`` is ``None`` or empty, the text is returned as-is
    (no markers are touched). This preserves backwards compatibility when
    citations are disabled on the chatbot.

    Args:
        response_text: The raw AI response text (may contain ``[X.Y]``
                       markers).
        cite_data: Parsed citation data dict mapping marker keys
                   (e.g. ``"3.4"``) to source metadata.

    Returns:
        The processed response text.
    """
    if not cite_data or not response_text:
        return response_text

    logger.debug(
        "Processing citations: %d markers in cite_data, text length %d",
        len(cite_data),
        len(response_text),
    )

    # Collect URL-type sources for the footer. Keyed by the link URL to
    # deduplicate (multiple markers can reference the same web page).
    url_sources: Dict[str, str] = {}  # url -> title

    # Build a set of marker keys that should be stripped (all of them).
    markers_to_strip: set = set()

    for marker_key, source_info in cite_data.items():
        if not isinstance(source_info, dict):
            logger.debug("Skipping non-dict citation entry: %s", marker_key)
            continue

        markers_to_strip.add(marker_key)
        source_type = source_info.get('type', '').lower()
        title = (
            source_info.get('title')
            or source_info.get('file_name')
            or 'Source'
        )

        if source_type == 'url':
            # Try to find a usable link for this source.
            link = (
                source_info.get('reference_source_link')
                or source_info.get('url')
                or source_info.get('file_name')
                or None
            )
            if link and _is_valid_url(link):
                # Deduplicate by URL; keep the first title seen.
                if link not in url_sources:
                    url_sources[link] = title
            else:
                logger.debug(
                    "URL-type citation '%s' has no valid link; stripping marker only",
                    marker_key,
                )

    # Strip all citation markers from the text.
    processed = _strip_citation_markers(response_text, markers_to_strip)

    # Append a "Sources" footer if we collected any URL sources.
    if url_sources:
        processed = _append_sources_footer(processed, url_sources)

    return processed


def _strip_citation_markers(text: str, marker_keys: set) -> str:
    """Remove ``[X.Y]`` markers from *text* for keys present in *marker_keys*.

    Only markers whose numeric key (e.g. ``3.4``) is in ``marker_keys``
    are removed. Markers not found in the citation data are left alone so
    we do not accidentally destroy intentional bracketed text like ``[1]``
    list items.

    After stripping, any resulting double-spaces or leading/trailing
    whitespace around the removed marker are cleaned up.
    """
    if not marker_keys:
        return text

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key in marker_keys:
            return ''
        return match.group(0)

    result = _CITATION_PATTERN.sub(_replace, text)

    # Clean up artefacts: collapse multiple spaces into one.
    result = re.sub(r'  +', ' ', result)
    # Remove spaces before punctuation that may have been left behind.
    result = re.sub(r' ([.,;:!?])', r'\1', result)

    return result.strip()


def _append_sources_footer(text: str, url_sources: Dict[str, str]) -> str:
    """Append a markdown "Sources" section to the response text.

    Args:
        text: The (already cleaned) response text.
        url_sources: Mapping of URL to display title.

    Returns:
        Text with appended sources footer.
    """
    lines = ["\n\n**Sources:**"]
    for idx, (url, title) in enumerate(url_sources.items(), start=1):
        # Sanitize title for markdown (remove brackets that would break links)
        clean_title = title.replace('[', '(').replace(']', ')')
        lines.append(f"{idx}. [{clean_title}]({url})")

    return text + '\n'.join(lines)


def _is_valid_url(value: str) -> bool:
    """Basic check that *value* looks like an HTTP(S) URL."""
    return isinstance(value, str) and value.startswith(('http://', 'https://'))


async def fetch_and_process_citations(
    api_client,
    session_uuid: str,
    response_text: str,
) -> str:
    """Convenience wrapper: fetch messages, extract citation data, process text.

    This is the main entry point called from the bot's command handlers.
    If anything goes wrong (network error, unexpected format) the original
    ``response_text`` is returned unchanged so the user always sees a
    response.

    Args:
        api_client: ``GPTTrainerAPI`` instance.
        session_uuid: The chat session UUID.
        response_text: The raw streamed response text.

    Returns:
        Processed response text (citations handled).
    """
    try:
        messages = await api_client.fetch_session_messages(session_uuid)
        cite_data = extract_cite_data(messages)

        if cite_data:
            logger.debug("Found citation data with %d entries", len(cite_data))
            return process_citations(response_text, cite_data)

        logger.debug("No citation data found for session %s", session_uuid[:8])
        return response_text

    except Exception as exc:
        # Never let citation processing break the response flow.
        logger.warning("Citation processing failed; returning raw text: %s", exc)
        return response_text
