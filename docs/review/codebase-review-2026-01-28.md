# Codebase Peer Review - Discord Bot

**Date**: 2026-01-28
**Branch**: `main`
**Scope**: Full codebase review (all source files)
**Reviewers**: pact-architect, pact-test-engineer, pact-backend-coder

---

## Consolidated Findings

### BLOCKING (7 unique issues - all 3 reviewers agreed on core set)

| # | Recommendation | File(s) | Reviewer(s) |
|---|---------------|---------|-------------|
| B1 | **aiohttp session destroyed after every command** - Singleton `api_client` used via `async with` closes session in `__aexit__`, defeating connection pooling and causing race conditions under concurrent usage | `api_client.py:45-55`, `main.py:137` | architect, test, backend |
| B2 | **Recursive retry in `get_response` risks cascading failures** - On failure, creates new session and recursively calls itself, amplifying load on failing API (up to 9 calls) and orphaning sessions | `api_client.py:152-158` | architect, test, backend |
| B3 | **`asyncio.Lock` held during entire stream response** - Serializes ALL API requests; a 10-30s streaming response blocks every other user's command | `api_client.py:68,107` | test, backend |
| B4 | **`commands.cooldown` silently does nothing on slash commands** - Uses prefix-command decorator on `app_commands`, so rate limiting is completely non-functional | `main.py:290,299` | architect, test, backend |
| B5 | **`setup_hook` swallows initialization errors** - If SessionManager or tree sync fails, bot continues in broken state; users get crashes on first command | `main.py:69-79` | test, backend |
| B6 | **`config.py` crashes at import with cryptic `KeyError`** - No validation or helpful error message when required env vars are missing | `config.py:81` | architect, test |
| B7 | **`seen_videos.json` lost on container restart** - Written to ephemeral container filesystem, not persistent volume; causes duplicate YouTube posts after every deploy | `content_scheduler.py:46` | architect, test |

### MINOR (14 unique deduplicated issues)

| # | Recommendation | File(s) | Reviewer(s) |
|---|---------------|---------|-------------|
| M1 | **`generate_image` calls synchronous Google API on event loop** - Blocks entire bot during image generation (seconds to tens of seconds) | `image_generator.py:150-167` | architect, test, backend |
| M2 | **Variable `config` shadowed by `ImageConfig`** - Latent bug; any future code using `config.SETTING` in that method gets wrong object | `main.py:262` | architect, test, backend |
| M3 | **Multiple conflicting `logging.basicConfig()` calls** - Only first import's config takes effect; actual log level depends on import order | `main.py:23`, `api_client.py:13`, `news_scraper.py:13`, `content_scheduler.py:18` | architect, test, backend |
| M4 | **Bare `except:` clauses catch SystemExit/KeyboardInterrupt** - Prevents clean shutdown, masks errors silently | `content_scheduler.py:232,250` | architect, test, backend |
| M5 | **`datetime.utcnow()` deprecated (Python 3.12+)** - Returns naive datetime; inconsistent with timezone-aware datetimes elsewhere | `session_manager.py:99,109` | architect, test, backend |
| M6 | **`asyncio.get_event_loop()` deprecated** - Should use `asyncio.get_running_loop()` | `content_scheduler.py:159` | architect, test, backend |
| M7 | **Channel history scanned twice on startup** - Two separate Discord API calls fetching same 100 messages | `content_scheduler.py:63-78` | architect, test, backend |
| M8 | **New `aiohttp.ClientSession` created per retry attempt** - Wasteful session creation in retry loop | `content_scraper.py:21` | architect, test, backend |
| M9 | **No `.dockerignore` file** - `.env`, `.venv/`, `.git/` copied into Docker image (security risk + bloat) | project root | architect |
| M10 | **Channel context concatenation has no size limit** - Potentially oversized input sent to GPT Trainer API | `main.py:233` | architect |
| M11 | **`.seconds` instead of `.total_seconds()` in scheduling** - Could compute wrong sleep duration if timedelta > 24h | `content_scheduler.py:281` | test, backend |
| M12 | **No input validation on command prompts** - No length or sanitization checks before sending to external APIs | `main.py:291,308` | test |
| M13 | **`posted_urls` not persisted; only last 100 messages scanned** - News articles could be re-posted after restart | `content_scheduler.py:51` | test, backend |
| M14 | **No command error handler for slash commands** - Unhandled exceptions show "Application did not respond" with no logging | `main.py` | backend |

### FUTURE (8 unique deduplicated issues)

| # | Recommendation | File(s) | Reviewer(s) |
|---|---------------|---------|-------------|
| F1 | **No test suite** - 0% coverage; no test files exist despite testable pure functions | project-wide | architect, test, backend |
| F2 | **Consolidate persistence into SQLite** - Currently uses SQLite + JSON file + in-memory sets; fragile and inconsistent | architecture | architect, test |
| F3 | **Add health check endpoint** - No way to detect hung process in Docker/Railway | infrastructure | architect, test, backend |
| F4 | **Pin all dependency versions** - Mix of `>=` and `==` makes builds non-reproducible | `requirements.txt` | architect, backend |
| F5 | **Separate bot init from command registration** - Importing `main.py` immediately creates bot; prevents testing | `main.py` | architect, backend |
| F6 | **Remove dead code/imports** - `OpenAI`, `scrape_article_content` imported but unused; deprecated `OPENAI_API_KEY` config | `main.py:16-17`, `config.py:36` | architect, backend |
| F7 | **`seen_videos` set grows unboundedly** - No pruning mechanism; file grows indefinitely over months | `content_scheduler.py` | test, backend |
| F8 | **Add graceful shutdown for scheduler tasks** - `stop()` cancels but doesn't await; in-flight operations lost | `content_scheduler.py:135-140` | test |

---

## Reviewer Agreement Analysis

**High agreement** across all 3 reviewers on the core blocking issues (B1-B4). The API client session lifecycle and non-functional cooldowns were independently identified by every reviewer as the most critical issues.

**No conflicts** between reviewers. Minor differences in severity classification (e.g., variable shadowing rated Blocking by some, Minor by others) resolved by consensus toward the more impactful rating.

---

## Merge Readiness

**Not applicable** - This is a codebase review on `main`, not a PR review. Findings represent the current state of the production code.
