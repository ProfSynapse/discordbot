"""
Tests for config.py -- BotConfig.from_env().

config.py calls BotConfig.from_env() at module level (line 91), which means
importing the module triggers validation. To test from_env() in isolation,
we import only the BotConfig class without triggering the module-level call.

We achieve this by reading config.py's source and extracting the BotConfig class
definition, or by carefully controlling imports.
"""

import os
import sys
import pytest
import importlib


def _import_bot_config_class():
    """Import BotConfig class without triggering the module-level from_env() call.

    We do this by reading the source, removing the `config = BotConfig.from_env()` line,
    and executing the rest in a clean namespace.
    """
    source_path = "/mnt/f/Code/discordbot/config.py"
    with open(source_path, "r") as f:
        source = f.read()

    # Remove the module-level instantiation line
    lines = source.split("\n")
    filtered = [line for line in lines if not line.strip().startswith("config = BotConfig.from_env()")]
    clean_source = "\n".join(filtered)

    namespace = {"__name__": "config_test_ns"}
    exec(clean_source, namespace)
    return namespace["BotConfig"]


BotConfig = _import_bot_config_class()


class TestBotConfigFromEnv:
    """Tests for BotConfig.from_env() class method."""

    REQUIRED_VARS = {
        "DISCORD_TOKEN": "test-discord-token",
        "GPT_TRAINER_TOKEN": "test-gpt-token",
        "CHATBOT_UUID": "test-chatbot-uuid",
        "GOOGLE_API_KEY": "test-google-key",
    }

    def _set_required_env(self, monkeypatch):
        """Set all required environment variables."""
        for key, value in self.REQUIRED_VARS.items():
            monkeypatch.setenv(key, value)

    def _clear_all_env(self, monkeypatch):
        """Remove all config-related environment variables."""
        all_vars = list(self.REQUIRED_VARS.keys()) + [
            "CONTENT_CHANNEL_ID", "YOUTUBE_API_KEY", "OPENAI_API_KEY",
            "SESSION_DB_PATH", "SESSION_MAX_AGE_DAYS", "USE_CHANNEL_CONTEXT",
            "CHANNEL_CONTEXT_LIMIT", "LOG_LEVEL", "MAX_MESSAGE_LENGTH",
            "MAX_HISTORY_MESSAGES", "RATE_LIMIT_DELAY", "CONVERSATION_HISTORY_FILE",
        ]
        for var in all_vars:
            monkeypatch.delenv(var, raising=False)

    # -------------------------------------------------------------------
    # Happy-path tests
    # -------------------------------------------------------------------

    def test_from_env_with_required_vars_only(self, monkeypatch):
        """Should succeed with only the four required variables set."""
        self._clear_all_env(monkeypatch)
        self._set_required_env(monkeypatch)

        cfg = BotConfig.from_env()

        assert cfg.DISCORD_TOKEN == "test-discord-token"
        assert cfg.GPT_TRAINER_TOKEN == "test-gpt-token"
        assert cfg.CHATBOT_UUID == "test-chatbot-uuid"
        assert cfg.GOOGLE_API_KEY == "test-google-key"

    def test_default_values(self, monkeypatch):
        """Optional fields should have sensible defaults when not set."""
        self._clear_all_env(monkeypatch)
        self._set_required_env(monkeypatch)

        cfg = BotConfig.from_env()

        assert cfg.CONTENT_CHANNEL_ID is None
        assert cfg.YOUTUBE_API_KEY is None
        assert cfg.OPENAI_API_KEY is None
        assert cfg.SESSION_DB_PATH == "/data/sessions.db"
        assert cfg.SESSION_MAX_AGE_DAYS == 0
        assert cfg.USE_CHANNEL_CONTEXT is True
        assert cfg.CHANNEL_CONTEXT_LIMIT == 5
        assert cfg.LOG_LEVEL == "INFO"
        assert cfg.MAX_MESSAGE_LENGTH == 2000
        assert cfg.RATE_LIMIT_DELAY == 1.0

    def test_optional_vars_are_picked_up(self, monkeypatch):
        """Optional environment variables should override defaults."""
        self._clear_all_env(monkeypatch)
        self._set_required_env(monkeypatch)
        monkeypatch.setenv("CONTENT_CHANNEL_ID", "123456789")
        monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key")
        monkeypatch.setenv("SESSION_DB_PATH", "/tmp/test.db")
        monkeypatch.setenv("SESSION_MAX_AGE_DAYS", "30")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        monkeypatch.setenv("MAX_MESSAGE_LENGTH", "4000")
        monkeypatch.setenv("RATE_LIMIT_DELAY", "2.5")

        cfg = BotConfig.from_env()

        assert cfg.CONTENT_CHANNEL_ID == 123456789
        assert cfg.YOUTUBE_API_KEY == "yt-key"
        assert cfg.SESSION_DB_PATH == "/tmp/test.db"
        assert cfg.SESSION_MAX_AGE_DAYS == 30
        assert cfg.LOG_LEVEL == "DEBUG"
        assert cfg.MAX_MESSAGE_LENGTH == 4000
        assert cfg.RATE_LIMIT_DELAY == 2.5

    def test_use_channel_context_boolean_parsing(self, monkeypatch):
        """USE_CHANNEL_CONTEXT should parse string booleans correctly."""
        self._clear_all_env(monkeypatch)
        self._set_required_env(monkeypatch)

        monkeypatch.setenv("USE_CHANNEL_CONTEXT", "false")
        cfg = BotConfig.from_env()
        assert cfg.USE_CHANNEL_CONTEXT is False

        monkeypatch.setenv("USE_CHANNEL_CONTEXT", "False")
        cfg = BotConfig.from_env()
        assert cfg.USE_CHANNEL_CONTEXT is False

        monkeypatch.setenv("USE_CHANNEL_CONTEXT", "TRUE")
        cfg = BotConfig.from_env()
        assert cfg.USE_CHANNEL_CONTEXT is True

        monkeypatch.setenv("USE_CHANNEL_CONTEXT", "true")
        cfg = BotConfig.from_env()
        assert cfg.USE_CHANNEL_CONTEXT is True

    # -------------------------------------------------------------------
    # Missing required variable tests
    # -------------------------------------------------------------------

    def test_missing_discord_token_raises(self, monkeypatch):
        """Should raise EnvironmentError when DISCORD_TOKEN is missing."""
        self._clear_all_env(monkeypatch)
        self._set_required_env(monkeypatch)
        monkeypatch.delenv("DISCORD_TOKEN")

        with pytest.raises(EnvironmentError, match="DISCORD_TOKEN"):
            BotConfig.from_env()

    def test_missing_gpt_trainer_token_raises(self, monkeypatch):
        """Should raise EnvironmentError when GPT_TRAINER_TOKEN is missing."""
        self._clear_all_env(monkeypatch)
        self._set_required_env(monkeypatch)
        monkeypatch.delenv("GPT_TRAINER_TOKEN")

        with pytest.raises(EnvironmentError, match="GPT_TRAINER_TOKEN"):
            BotConfig.from_env()

    def test_missing_chatbot_uuid_raises(self, monkeypatch):
        """Should raise EnvironmentError when CHATBOT_UUID is missing."""
        self._clear_all_env(monkeypatch)
        self._set_required_env(monkeypatch)
        monkeypatch.delenv("CHATBOT_UUID")

        with pytest.raises(EnvironmentError, match="CHATBOT_UUID"):
            BotConfig.from_env()

    def test_missing_google_api_key_raises(self, monkeypatch):
        """Should raise EnvironmentError when GOOGLE_API_KEY is missing."""
        self._clear_all_env(monkeypatch)
        self._set_required_env(monkeypatch)
        monkeypatch.delenv("GOOGLE_API_KEY")

        with pytest.raises(EnvironmentError, match="GOOGLE_API_KEY"):
            BotConfig.from_env()

    def test_missing_all_required_vars_raises(self, monkeypatch):
        """Should raise EnvironmentError listing all missing variables."""
        self._clear_all_env(monkeypatch)

        with pytest.raises(EnvironmentError) as exc_info:
            BotConfig.from_env()

        error_msg = str(exc_info.value)
        for var in self.REQUIRED_VARS:
            assert var in error_msg

    def test_missing_multiple_required_vars_lists_all(self, monkeypatch):
        """Error message should list all missing vars, not just the first."""
        self._clear_all_env(monkeypatch)
        monkeypatch.setenv("DISCORD_TOKEN", "token")
        # Missing: GPT_TRAINER_TOKEN, CHATBOT_UUID, GOOGLE_API_KEY

        with pytest.raises(EnvironmentError) as exc_info:
            BotConfig.from_env()

        error_msg = str(exc_info.value)
        assert "GPT_TRAINER_TOKEN" in error_msg
        assert "CHATBOT_UUID" in error_msg
        assert "GOOGLE_API_KEY" in error_msg

    # -------------------------------------------------------------------
    # Edge cases
    # -------------------------------------------------------------------

    def test_content_channel_id_type_conversion(self, monkeypatch):
        """CONTENT_CHANNEL_ID should be converted to int."""
        self._clear_all_env(monkeypatch)
        self._set_required_env(monkeypatch)
        monkeypatch.setenv("CONTENT_CHANNEL_ID", "987654321012345678")

        cfg = BotConfig.from_env()
        assert cfg.CONTENT_CHANNEL_ID == 987654321012345678
        assert isinstance(cfg.CONTENT_CHANNEL_ID, int)

    def test_channel_context_limit_type_conversion(self, monkeypatch):
        """CHANNEL_CONTEXT_LIMIT should be converted to int."""
        self._clear_all_env(monkeypatch)
        self._set_required_env(monkeypatch)
        monkeypatch.setenv("CHANNEL_CONTEXT_LIMIT", "10")

        cfg = BotConfig.from_env()
        assert cfg.CHANNEL_CONTEXT_LIMIT == 10
        assert isinstance(cfg.CHANNEL_CONTEXT_LIMIT, int)
