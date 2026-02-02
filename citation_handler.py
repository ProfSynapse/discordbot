"""
Location: /mnt/f/Code/discordbot/citation_handler.py
Summary: Processes GPT Trainer citation data and transforms response text.

    When ``show_citations`` is enabled on the GPT Trainer chatbot, the AI
    embeds ``[X.Y]`` markers in its response text and the message object
    carries a ``cite_data_json`` field mapping those markers to source
    metadata (title, file name, type, chunk text, etc.).

    This module:
    - Parses ``cite_data_json`` from the most recent assistant message
    - For **URL-type** sources: replaces ``[X.Y]`` markers with inline
      parenthetical markdown hyperlinks ``([title](<url>))`` right where
      they appear in the text. Angle brackets suppress Discord embed
      previews. Adjacent citations pointing to the same URL are deduplicated.
    - For **upload/file-type** sources: strips the ``[X.Y]`` markers from
      the response text entirely (no useful link to show the user)
    - Passes text through unchanged when no citation data is present

Used by: main.py (``/prof`` command and ``on_message`` handler)
"""

import json
import logging
import re
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Matches citation markers like [1.2], [23.4], [3.10].
_CITATION_PATTERN = re.compile(r'\[(\d+(?:\.\d+)?)\]')

# Maximum display length for a citation title before truncation.
_MAX_TITLE_LENGTH = 50


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
    - **url** (web sources): The ``[X.Y]`` marker is replaced with an
      inline parenthetical hyperlink ``([title](<url>))`` at the exact
      position where the marker appears. Angle brackets suppress Discord
      embed previews. Adjacent markers that resolve to the same URL are
      deduplicated into a single hyperlink.
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

    # Build a lookup: marker_key -> (url, title) or None for non-URL types.
    marker_lookup: Dict[str, Optional[Tuple[str, str]]] = {}

    for marker_key, source_info in cite_data.items():
        if not isinstance(source_info, dict):
            logger.debug("Skipping non-dict citation entry: %s", marker_key)
            continue

        source_type = source_info.get('type', '').lower()
        title = (
            source_info.get('title')
            or source_info.get('file_name')
            or 'Source'
        )

        # If the title looks like a URL (common when title is empty and
        # file_name is the URL itself), extract just the domain name.
        if _is_valid_url(title):
            title = _extract_domain(title)

        if source_type == 'url':
            link = (
                source_info.get('reference_source_link')
                or source_info.get('url')
                or source_info.get('file_name')
                or None
            )
            if link and _is_valid_url(link):
                marker_lookup[marker_key] = (link, title)
            else:
                logger.debug(
                    "URL-type citation '%s' has no valid link; stripping marker only",
                    marker_key,
                )
                marker_lookup[marker_key] = None
        else:
            # Upload/file/other types: strip the marker, no link.
            marker_lookup[marker_key] = None

    processed = _replace_citation_markers(response_text, marker_lookup)

    return processed


def _replace_citation_markers(
    text: str,
    marker_lookup: Dict[str, Optional[Tuple[str, str]]],
) -> str:
    """Replace or strip ``[X.Y]`` markers in *text* based on *marker_lookup*.

    For markers that map to a ``(url, title)`` tuple, the marker is
    replaced with an inline parenthetical hyperlink ``([title](<url>))``.
    Adjacent markers that resolve to the **same URL** are collapsed
    into a single hyperlink to avoid repetition.

    For markers that map to ``None`` (upload/file types), the marker
    is simply removed.

    Markers not found in ``marker_lookup`` are handled based on format:

    - **Decimal markers** (e.g., ``[73.1]``): Stripped. These are clearly
      GPT Trainer citation markers from PDF/file sources that didn't
      generate corresponding entries in cite_data.
    - **Integer-only markers** (e.g., ``[1]``): Preserved. These might be
      intentional bracketed text like numbered list items.

    After processing, whitespace artefacts (double spaces, spaces
    before punctuation) are cleaned up.
    """
    if not marker_lookup:
        return text

    # We process the text by scanning for runs of adjacent citation
    # markers. A "run" is one or more [X.Y] markers separated only by
    # optional whitespace. For each run, we collect the unique URLs
    # they resolve to and emit one hyperlink per unique URL (in order
    # of first appearance). Markers that resolve to None (strip-only)
    # contribute nothing to the output for that run.

    # Pattern to match a run of one or more adjacent [X.Y] markers.
    # Each marker is captured individually via finditer inside the
    # replacement function.
    _run_pattern = re.compile(
        r'(\[\d+(?:\.\d+)?\](?:\s*\[\d+(?:\.\d+)?\])*)'
    )

    def _replace_run(match: re.Match) -> str:
        """Replace a run of adjacent citation markers.

        Handling of unrecognized markers (not in marker_lookup):
        - Markers WITH decimals (e.g., ``[73.1]``) are stripped. These are
          clearly GPT Trainer citation markers from PDF/file sources that
          didn't get entries in cite_data.
        - Markers WITHOUT decimals (e.g., ``[1]``) are preserved. These
          might be intentional bracketed text like numbered list items.
        """
        run_text = match.group(0)
        individual_markers = _CITATION_PATTERN.findall(run_text)

        # Check if ANY marker in this run is recognized OR is a decimal
        # marker (which is clearly a citation even if not in lookup).
        has_known_marker = any(m in marker_lookup for m in individual_markers)
        has_decimal_marker = any('.' in m for m in individual_markers)

        if not has_known_marker and not has_decimal_marker:
            # All markers are integer-only and unrecognized - likely list
            # items like [1], [2], etc. Leave the entire run untouched.
            return run_text

        # Collect unique (url, title) pairs in order, deduplicating by URL.
        # Also track integer-only markers that should be preserved.
        seen_urls: set = set()
        hyperlinks: list = []
        preserved_markers: list = []

        for key in individual_markers:
            info = marker_lookup.get(key)
            if info is None:
                # Unrecognized marker: strip if decimal, preserve if integer-only.
                if '.' in key:
                    # Decimal marker (e.g., "73.1") - clearly a citation, strip it.
                    continue
                else:
                    # Integer-only marker (e.g., "1") - might be a list item, preserve.
                    preserved_markers.append(f'[{key}]')
                    continue
            url, title = info
            if url not in seen_urls:
                seen_urls.add(url)
                hyperlinks.append(_format_hyperlink(title, url))

        # Build output: hyperlinks first, then any preserved markers.
        output_parts = hyperlinks + preserved_markers
        if output_parts:
            return ' '.join(output_parts)

        # All markers in the run were strip-only (no URLs, no preserved markers).
        return ''

    result = _run_pattern.sub(_replace_run, text)

    # Clean up artefacts: collapse multiple spaces into one.
    result = re.sub(r'  +', ' ', result)
    # Remove spaces before punctuation that may have been left behind.
    result = re.sub(r' ([.,;:!?])', r'\1', result)

    return result.strip()


def _format_hyperlink(title: str, url: str) -> str:
    """Format a title and URL as a Discord markdown hyperlink.

    Sanitizes the title for markdown (removes brackets that would break
    the link syntax) and truncates long titles to ``_MAX_TITLE_LENGTH``
    characters.

    Args:
        title: Display text for the hyperlink.
        url: The link target.

    Returns:
        A parenthetical markdown hyperlink string like ``([title](<url>))``.
        The outer parentheses make it read as a natural inline reference.
        The angle brackets around the URL suppress Discord's automatic
        embed preview cards.
    """
    # Sanitize brackets that would break markdown link syntax.
    clean_title = title.replace('[', '(').replace(']', ')')

    # Truncate long titles.
    if len(clean_title) > _MAX_TITLE_LENGTH:
        clean_title = clean_title[:_MAX_TITLE_LENGTH - 3].rstrip() + '...'

    return f'([{clean_title}](<{url}>))'


def _is_valid_url(value: str) -> bool:
    """Basic check that *value* looks like an HTTP(S) URL."""
    return isinstance(value, str) and value.startswith(('http://', 'https://'))


def _extract_domain(url: str) -> str:
    """Extract the domain name from a URL, stripping 'www.' prefix if present."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split('/')[0]
        if domain.startswith('www.'):
            domain = domain[4:]
        return domain if domain else 'Source'
    except Exception:
        return 'Source'


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
