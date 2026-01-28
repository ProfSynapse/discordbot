# Architectural Review: Discord Bot Codebase

**Reviewer**: pact-architect
**Date**: 2026-01-28
**Scope**: Full codebase review on `main` branch
**Files Reviewed**: main.py, api_client.py, image_generator.py, config.py, session_manager.py, scraper/content_scheduler.py, scraper/news_scraper.py, scraper/content_scraper.py, Dockerfile, requirements.txt, .gitignore

---

## Executive Summary

The codebase is a moderately well-structured Discord bot with clear module separation. The core chat, image generation, and content scheduling domains each have dedicated modules, which is good. However, several issues span across the codebase -- most notably around the API client session lifecycle, a recursive retry pattern that risks infinite loops, and configuration that crashes on import if environment variables are missing.

---

## BLOCKING: Critical Issues

### B1. Recursive Retry in `api_client.py` Can Create Infinite Retry Chain

**File**: `api_client.py:152-158`
**What**: When `get_response()` fails, it catches the exception, creates a brand-new session via `create_chat_session()`, and then **recursively calls itself** with the new session. If the underlying problem is not session-specific (e.g., network outage, API downtime, rate limiting), this recursive call will also fail, trigger the same catch block, create yet another session, and call itself again -- up to the retry depth of `_make_request` (3 retries per call). Each recursive call chains 3 more retries, leading to 3 x 3 = 9 API calls before finally failing. Meanwhile, orphaned sessions accumulate on the GPT Trainer side.

**Why It Matters**: During an API outage, every user message triggers up to 9 API calls and creates an orphaned session. This amplifies load on an already-struggling API and wastes quota. In a worst case with many concurrent users, this becomes a self-inflicted denial-of-service.

**Fix**: Replace the recursive fallback with a simple flag or iteration. If the first attempt fails, try once with a new session, but do not recurse:

```python
async def get_response(self, session_uuid: str, message: str, context: str = "", _is_retry: bool = False) -> str:
    try:
        # ... existing streaming logic ...
    except Exception as e:
        if not _is_retry:
            new_session_uuid = await self.create_chat_session()
            return await self.get_response(new_session_uuid, message, context, _is_retry=True)
        return "I'm having trouble processing your request."
```

---

### B2. API Client Session Lifecycle is Broken (Session Destroyed After Every Request)

**File**: `api_client.py:45-55` (context manager) and `main.py:137` (usage)
**What**: `GPTTrainerAPI` is used as an async context manager in `main.py:137` (`async with api_client as client:`). The `__aexit__` method at line 54 **closes the aiohttp session and sets it to None** every time the context manager exits. Since `api_client` is a module-level singleton, this means the HTTP connection pool is destroyed after every single `/prof` command, then recreated on the next call.

Additionally, `content_scheduler.py:477` also uses `async with api_client as client:`, creating the same destroy-and-recreate cycle for scheduled content uploads.

**Why It Matters**:
1. Connection pooling is completely negated -- every request creates a new TCP connection with TLS handshake, adding ~50-200ms latency per request.
2. Race condition: if two users send `/prof` simultaneously, one user's `__aexit__` could close the session while the other user's request is in flight, causing an `aiohttp.ClientError`.

**Fix**: The singleton should manage its own session lifecycle separate from per-request context managers. Either:
- Remove the context manager pattern and create the session in `setup_hook()` / close in bot `close()`
- Or make `__aexit__` a no-op and add an explicit `close()` method called only at shutdown

---

### B3. `config.py` Crashes at Import Time if Environment Variables Are Missing

**File**: `config.py:81`
**What**: `config = BotConfig.from_env()` executes at module import time. If any required environment variable (`DISCORD_TOKEN`, `GPT_TRAINER_TOKEN`, `CHATBOT_UUID`, `GOOGLE_API_KEY`) is missing, this raises a `KeyError` with no helpful error message -- just `KeyError: 'DISCORD_TOKEN'`.

Since every other module imports `from config import config`, a missing env var produces a cryptic traceback originating from whichever module was imported first.

**Why It Matters**: New developers, CI/CD pipelines, or testing environments get an unhelpful crash. There is no validation, no error message listing which variables are missing.

**Fix**: Add validation in `from_env()` that checks all required variables before constructing the object:

```python
@classmethod
def from_env(cls) -> 'BotConfig':
    required = ['DISCORD_TOKEN', 'GPT_TRAINER_TOKEN', 'CHATBOT_UUID', 'GOOGLE_API_KEY']
    missing = [var for var in required if var not in os.environ]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            f"Set these in your .env file or environment."
        )
    return cls(...)
```

---

### B4. `seen_videos.json` Written to Container Working Directory (Data Loss on Redeploy)

**File**: `content_scheduler.py:46`
**What**: `self.seen_videos_file = 'seen_videos.json'` writes to the current working directory (`/app` inside Docker). The SQLite session database correctly uses a Railway volume mount (`/data/sessions.db`), but `seen_videos.json` does not. On every container restart or redeploy, this file is lost.

**Why It Matters**: After every deploy, the bot re-posts all YouTube videos it has seen before, flooding the content channel with duplicates. The `content_channel.history(limit=100)` check on startup partially mitigates this by scanning recent messages, but it only catches the last 100 messages and does not cover all previously seen videos.

**Fix**: Move `seen_videos.json` to the persistent volume path, e.g., `/data/seen_videos.json`, or better yet, add a `seen_videos` table to the SQLite database.

---

## MINOR: Issues Worth Fixing

### M1. Variable Name Shadowing: `config` Shadowed in `generate_image` Method

**File**: `main.py:262`
**What**: `clean_prompt, config = self.image_generator.parse_flags(prompt)` shadows the module-level `config` import (`from config import config`). Within the rest of the `generate_image` method, `config` refers to the `ImageConfig` dataclass, not the bot configuration. This works by accident because the bot config is not used later in that method, but it is confusing and fragile.

**Why It Matters**: If someone later adds code in `generate_image` that needs the bot config (e.g., `config.GOOGLE_API_KEY`), they will get an `AttributeError` on `ImageConfig` with no obvious explanation.

**Fix**: Rename the local variable: `clean_prompt, img_config = self.image_generator.parse_flags(prompt)`

---

### M2. Cooldown Decorator Has No Effect on Slash Commands

**File**: `main.py:290, 299`
**What**: `@commands.cooldown(1, 60, commands.BucketType.user)` is applied to app commands (slash commands registered via `bot.tree.command`). However, `commands.cooldown` is designed for prefix-based commands (`commands.Command`), not `app_commands`. This decorator silently does nothing -- there is no actual rate limiting on `/prof` or `/image`.

**Why It Matters**: Users can spam the commands without any cooldown, potentially exhausting API quotas (GPT Trainer, Google Imagen, YouTube Data API). This is both a cost and abuse concern.

**Fix**: Implement rate limiting using `app_commands.checks.cooldown()` or a custom check:

```python
from discord.app_commands import checks

@bot.tree.command(name="prof", description="Chat with Professor Synapse")
@checks.cooldown(1, 60, key=lambda i: (i.guild_id, i.user.id))
async def prof_command(interaction: discord.Interaction, *, prompt: str):
    ...
```

---

### M3. Multiple Conflicting `logging.basicConfig()` Calls

**File**: `main.py:23`, `api_client.py:13`, `news_scraper.py:13`, `content_scheduler.py:18`
**What**: `logging.basicConfig()` is called in four different modules with different configurations. Only the first call to `basicConfig()` takes effect (Python logging behavior) -- subsequent calls are silently ignored. Depending on import order, the logging configuration could come from any of these modules.

**Why It Matters**: `main.py` configures DEBUG level with file output, but if `api_client` or `news_scraper` is imported first, logging is configured at INFO level without file output. The actual behavior depends on import order, which is fragile and hard to debug.

**Fix**: Remove `logging.basicConfig()` from all files except `main.py`. All other modules should only use `logging.getLogger(__name__)`.

---

### M4. `_build_channel_context` Fetches Unbounded Message Content

**File**: `main.py:233`
**What**: `channel.history(limit=limit * 2)` fetches recent messages and concatenates their full content. With the default `CHANNEL_CONTEXT_LIMIT=5`, this fetches 10 messages. The concatenated context is then prepended to the user's query and sent to the GPT Trainer API. There is no limit on the total size of the context string.

**Why It Matters**: If channel messages are long, the context string could be very large, potentially exceeding API input limits or consuming unnecessary tokens. The API endpoint's behavior with oversized input is undefined.

**Fix**: Add a character limit to the total context:

```python
MAX_CONTEXT_CHARS = 2000
if len("\n".join(context)) > MAX_CONTEXT_CHARS:
    # Truncate from oldest messages first
    ...
```

---

### M5. Bare `except:` Clauses in Content Scheduler

**File**: `content_scheduler.py:232`, `content_scheduler.py:250`
**What**: Two bare `except:` clauses catch all exceptions including `KeyboardInterrupt`, `SystemExit`, and `MemoryError`. These silently return `False` or `'Unknown date'` respectively.

**Why It Matters**: Bare `except:` can mask serious errors. If `_is_new_and_recent` fails due to a programming error, all articles are silently filtered out with no logging, making the bug invisible.

**Fix**: Change to `except Exception:` at minimum, and add logging:

```python
except Exception as e:
    logger.warning(f"Error checking article recency: {e}")
    return False
```

---

### M6. `datetime.utcnow()` is Deprecated (Python 3.12+)

**File**: `session_manager.py:99, 109, 199`
**What**: Uses `datetime.utcnow()` which is deprecated in Python 3.12+ and returns a naive datetime (no timezone info). Meanwhile, `content_scheduler.py` and `news_scraper.py` use timezone-aware datetimes with `pytz.UTC`.

**Why It Matters**: Mixing naive and timezone-aware datetimes can cause `TypeError` in comparisons. The `session_manager` stores ISO timestamps without timezone info while the scraper stores them with timezone info. This inconsistency could cause bugs if timestamps are ever compared across modules.

**Fix**: Use `datetime.now(timezone.utc)` throughout:

```python
from datetime import datetime, timezone
now = datetime.now(timezone.utc).isoformat()
```

---

### M7. `asyncio.get_event_loop()` is Deprecated

**File**: `content_scheduler.py:159`
**What**: `asyncio.get_event_loop().run_in_executor(None, request.execute)` uses the deprecated `get_event_loop()`. In Python 3.12+, this may raise a `DeprecationWarning` and will eventually be removed.

**Fix**: Use `asyncio.get_running_loop().run_in_executor(None, request.execute)` or `await asyncio.to_thread(request.execute)`.

---

### M8. No `.dockerignore` File

**File**: Project root
**What**: There is no `.dockerignore` file. The `COPY . .` in the Dockerfile copies everything -- including `.venv/`, `__pycache__/`, `.git/`, `bot.log`, potentially `.env` files, and the CLAUDE.md/docs files.

**Why It Matters**:
1. **Security risk**: If `.env` exists locally and is copied into the Docker image, secrets could be baked into the image layer (visible via `docker history`).
2. **Build bloat**: `.venv/` and `.git/` add significant size to the build context and image.

**Fix**: Create a `.dockerignore`:

```
.venv/
__pycache__/
.git/
.env*
*.log
docs/
.claude/
CLAUDE.md
```

---

### M9. Duplicate Channel History Scan on Startup

**File**: `content_scheduler.py:63-78`
**What**: The `start()` method scans `self.content_channel.history(limit=100)` twice -- once at line 63 to check for existing video embeds, and again at line 73 to check for posted URLs. These are two separate API calls scanning the same 100 messages.

**Fix**: Combine into a single scan:

```python
async for message in self.content_channel.history(limit=100):
    if message.embeds:
        for embed in message.embeds:
            if embed.url:
                self.seen_videos.add(embed.url)
    urls = [word for word in message.content.split()
           if word.startswith(("http://", "https://"))]
    self.posted_urls.update(urls)
```

---

### M10. `image_generator.generate_image` is Synchronous (Blocking)

**File**: `image_generator.py:136-178`
**What**: The method is declared `async` but `self.client.models.generate_images()` is a synchronous Google genai SDK call. Running a synchronous HTTP call in an async method blocks the entire event loop.

**Why It Matters**: While an image is being generated (potentially several seconds), the bot cannot process any other commands, messages, or scheduler events. With multiple concurrent users, this creates noticeable lag.

**Fix**: Wrap the synchronous call in `asyncio.to_thread()`:

```python
response = await asyncio.to_thread(
    self.client.models.generate_images,
    model=config.model.value,
    prompt=prompt,
    config=GenerateImagesConfig(...)
)
```

---

### M11. `content_scraper.py` Creates a New `aiohttp.ClientSession` per Retry

**File**: `content_scraper.py:21`
**What**: Inside the retry loop, a new `aiohttp.ClientSession` is created on every attempt. Since the session is created inside the `for attempt in range(max_retries)` loop, each retry creates and destroys a session.

**Fix**: Move session creation outside the retry loop, or accept a session parameter.

---

## FUTURE: Improvements for Future Work

### F1. Consolidate State Persistence Strategy

Currently the bot uses three different persistence mechanisms:
1. **SQLite** (`session_manager.py`) for user sessions -- good
2. **JSON file** (`seen_videos.json`) for YouTube deduplication -- fragile
3. **In-memory sets** (`posted_urls`, `scraped_urls`) for news deduplication -- lost on restart

**Recommendation**: Migrate `seen_videos` and `posted_urls` into the SQLite database. This consolidates persistence, provides atomic operations, and benefits from the same volume mount.

---

### F2. Add Health Check Endpoint

The bot has no health check mechanism. Railway and Docker support health checks to detect when a service is unresponsive.

**Recommendation**: Add a lightweight HTTP health check endpoint (e.g., using `aiohttp.web`) or implement Discord's heartbeat monitoring to detect and recover from hung states.

---

### F3. Structured Logging

All logging uses unstructured string formatting. For production debugging and monitoring, structured logging (JSON format) would enable better log aggregation and searching.

**Recommendation**: Consider `structlog` or Python's built-in JSON formatter for production.

---

### F4. Dependency Pinning in `requirements.txt`

Some dependencies use `>=` (e.g., `aiohttp>=3.8.4`, `openai>=1.3.0`) while others are pinned exactly (e.g., `discord.py==2.2.3`). The `>=` constraints mean builds are not reproducible -- a new major version of `aiohttp` or `openai` could break the bot silently.

**Recommendation**: Pin all dependencies to exact versions, or use a lockfile (`pip-compile`, `poetry.lock`). The `discord.py==2.2.3` pinning is good practice that should be applied consistently.

---

### F5. Separate Bot Initialization from Command Registration

`main.py` mixes class definition, singleton instantiation, and command registration at module scope (lines 287-378). This makes testing difficult -- importing `main.py` immediately creates a bot instance and tries to connect.

**Recommendation**: Move command registration into a function (`register_commands(bot)`) and guard the bot creation behind `if __name__ == "__main__"`.

---

### F6. Content Scheduler is Tightly Coupled to Bot

`ContentScheduler` directly accesses `self.bot.get_channel()` and sends messages through Discord objects. This makes it impossible to test without a live Discord connection.

**Recommendation**: Define an abstract `ContentPublisher` interface that `ContentScheduler` uses to post content. The bot provides a Discord-specific implementation.

---

### F7. Dead Code and Unused Imports

- `main.py:17`: `from scraper.content_scraper import scrape_article_content` is imported but never used
- `main.py:16`: `from openai import OpenAI` is imported but never used
- `config.py:36`: `OPENAI_API_KEY` is marked as deprecated but still present
- `config.py:49`: `CONVERSATION_HISTORY_FILE` is defined but appears unused anywhere

**Recommendation**: Remove dead imports and deprecated configuration fields.

---

### F8. No Test Suite

There are no test files in the repository. The `.gitignore` references `Tests/` and `test_sessions_local.py`, suggesting tests existed at some point but were removed or never committed.

**Recommendation**: Add at minimum:
- Unit tests for `config.py` validation logic
- Unit tests for `image_generator.parse_flags()`
- Unit tests for `_truncate_response()`
- Integration tests for `session_manager.py` (can test with in-memory SQLite)

---

## Architecture Diagram

```
                    Discord Users
                         |
                    [Discord API]
                         |
                   +-----+-----+
                   | main.py   |
                   | DiscordBot|
                   +-----+-----+
                         |
          +--------------+--------------+
          |              |              |
    +-----+-----+  +----+----+  +------+------+
    | api_client |  | image_  |  | session_    |
    | GPTTrainer |  | generat |  | manager.py  |
    | API.py     |  | or.py   |  | (SQLite)    |
    +-----+------+  +----+----+  +------+------+
          |              |              |
    [GPT Trainer]  [Google Imagen] [/data/sessions.db]
          |
    +-----+------+
    | content_   |
    | scheduler  |
    +-----+------+
          |
     +----+----+
     |         |
+----+---+ +---+--------+
| news_  | | YouTube    |
| scraper| | Data API   |
+--------+ +------------+
```

---

## Summary Table

| ID | Severity | Component | Issue |
|----|----------|-----------|-------|
| B1 | BLOCKING | api_client.py | Recursive retry creates infinite retry chain |
| B2 | BLOCKING | api_client.py | HTTP session destroyed after every request |
| B3 | BLOCKING | config.py | Crashes at import with cryptic error if env vars missing |
| B4 | BLOCKING | content_scheduler.py | seen_videos.json lost on container restart |
| M1 | MINOR | main.py | Variable name `config` shadowed by `ImageConfig` |
| M2 | MINOR | main.py | `commands.cooldown` does nothing on slash commands |
| M3 | MINOR | multiple | Multiple conflicting `logging.basicConfig()` calls |
| M4 | MINOR | main.py | Channel context concatenation has no size limit |
| M5 | MINOR | content_scheduler.py | Bare `except:` clauses mask errors |
| M6 | MINOR | session_manager.py | `datetime.utcnow()` is deprecated |
| M7 | MINOR | content_scheduler.py | `asyncio.get_event_loop()` is deprecated |
| M8 | MINOR | project root | No `.dockerignore` -- secrets and bloat in image |
| M9 | MINOR | content_scheduler.py | Duplicate channel history scan on startup |
| M10 | MINOR | image_generator.py | Synchronous API call blocks event loop |
| M11 | MINOR | content_scraper.py | New HTTP session per retry attempt |
| F1 | FUTURE | architecture | Consolidate persistence (SQLite for everything) |
| F2 | FUTURE | infrastructure | Add health check endpoint |
| F3 | FUTURE | infrastructure | Structured logging |
| F4 | FUTURE | dependencies | Pin all dependency versions |
| F5 | FUTURE | main.py | Separate bot init from command registration |
| F6 | FUTURE | content_scheduler.py | Decouple scheduler from Discord |
| F7 | FUTURE | multiple | Remove dead code and unused imports |
| F8 | FUTURE | project | No test suite |
