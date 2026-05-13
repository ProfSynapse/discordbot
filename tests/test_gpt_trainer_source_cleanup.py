"""
Tests for GPT Trainer data source cleanup.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

import scraper.content_scheduler as content_scheduler
from api_client import GPTTrainerAPI
from config import config
from scraper.content_scheduler import ContentScheduler


class FakeGPTTrainerClient:
    def __init__(self, sources):
        self.sources = sources
        self.fetch_data_sources = AsyncMock(return_value=sources)
        self.delete_data_sources = AsyncMock(return_value={"success": True})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


@pytest.mark.asyncio
async def test_api_client_fetch_data_sources_normalizes_list(monkeypatch):
    client = GPTTrainerAPI()
    client._make_request = AsyncMock(return_value=[{"uuid": "source-1"}])

    result = await client.fetch_data_sources()

    assert result == [{"uuid": "source-1"}]
    client._make_request.assert_awaited_once_with(
        "GET",
        "chatbot/test-chatbot-uuid/data-sources",
    )


@pytest.mark.asyncio
async def test_api_client_delete_data_sources_uses_bulk_endpoint(monkeypatch):
    client = GPTTrainerAPI()
    client._make_request = AsyncMock(return_value={"success": True})

    result = await client.delete_data_sources(["source-1", "source-2"])

    assert result["success"] is True
    assert result["deleted"] == 2
    client._make_request.assert_awaited_once_with(
        "POST",
        "data-sources/delete",
        json={"uuids": ["source-1", "source-2"]},
    )


@pytest.mark.asyncio
async def test_cleanup_deletes_only_old_eligible_link_sources(monkeypatch):
    scheduler = ContentScheduler.__new__(ContentScheduler)
    scheduler._get_seen_content_older_than = AsyncMock(return_value=set())

    old_date = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    recent_date = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    sources = [
        {
            "uuid": "old-link",
            "type": "link",
            "created_at": old_date,
            "file_name": "https://example.com/old",
        },
        {
            "uuid": "recent-link",
            "type": "link",
            "created_at": recent_date,
            "file_name": "https://example.com/recent",
        },
        {
            "uuid": "old-url",
            "type": "url",
            "created_at": old_date,
            "file_name": "https://example.com/old-url",
        },
        {
            "uuid": "old-file",
            "type": "file",
            "created_at": old_date,
            "file_name": "memory.md",
        },
        {
            "uuid": "failed-recent-url",
            "type": "url",
            "status": "error:token",
            "created_at": recent_date,
            "file_name": "https://example.com/failed",
        },
    ]
    fake_client = FakeGPTTrainerClient(sources)

    monkeypatch.setattr(config, "GPT_TRAINER_SOURCE_RETENTION_DAYS", 365)
    monkeypatch.setattr(config, "GPT_TRAINER_SOURCE_CLEANUP_BATCH_SIZE", 50)
    monkeypatch.setattr(config, "GPT_TRAINER_SOURCE_CLEANUP_TYPES", {"url", "link"})
    monkeypatch.setattr(
        config,
        "GPT_TRAINER_SOURCE_CLEANUP_ERROR_STATUSES",
        {"error", "error:storage", "error:token", "fail"},
    )
    monkeypatch.setattr(content_scheduler, "api_client", fake_client)

    deleted = await scheduler._cleanup_old_gpt_trainer_sources()

    assert deleted == 3
    fake_client.delete_data_sources.assert_awaited_once_with([
        "old-link",
        "old-url",
        "failed-recent-url",
    ])


@pytest.mark.asyncio
async def test_cleanup_disabled_when_retention_is_zero(monkeypatch):
    scheduler = ContentScheduler.__new__(ContentScheduler)
    fake_client = FakeGPTTrainerClient([{"uuid": "old-link"}])

    monkeypatch.setattr(config, "GPT_TRAINER_SOURCE_RETENTION_DAYS", 0)
    monkeypatch.setattr(content_scheduler, "api_client", fake_client)

    deleted = await scheduler._cleanup_old_gpt_trainer_sources()

    assert deleted == 0
    fake_client.fetch_data_sources.assert_not_called()
    fake_client.delete_data_sources.assert_not_called()
