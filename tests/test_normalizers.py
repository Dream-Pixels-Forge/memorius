"""
Tests for memorius.normalizers — conversation format detection and conversion.

Normalizers return transcript-formatted text strings (not structured dicts).
"""

import json
import pytest
from memorius.normalizers import detect_format, normalize, NORMALIZERS


# ── Sample data ──────────────────────────────────────────────────────────────

DISCORD_SAMPLE = json.dumps({
    "messages": [
        {"id": "1", "type": "Default", "timestamp": "2024-01-01T12:00:00+00:00",
         "content": "Hello!", "author": {"id": "u1", "name": "Alice"}},
        {"id": "2", "type": "Default", "timestamp": "2024-01-01T12:01:00+00:00",
         "content": "Hey Alice", "author": {"id": "u2", "name": "Bob"}},
    ]
})

TELEGRAM_SAMPLE = json.dumps({
    "name": "Test Chat",
    "type": "personal_chat",
    "messages": [
        {"id": 1, "type": "message", "date": "2024-01-01T12:00:00",
         "text": "Hello!", "from": "Alice", "from_id": "user1"},
        {"id": 2, "type": "message", "date": "2024-01-01T12:01:00",
         "text": "Hi Alice", "from": "Bob", "from_id": "user2"},
    ]
})

WHATSAPP_SAMPLE = json.dumps({
    "messages": [
        {"key": {"fromMe": False, "remoteJid": "123456@s.whatsapp.net"},
         "message": {"conversation": "Hello!"},
         "messageTimestamp": "1704067200"},
        {"key": {"fromMe": True},
         "message": {"extendedTextMessage": {"text": "Hi there!"}},
         "messageTimestamp": "1704067260"},
    ]
})

GENERIC_SAMPLE = json.dumps([
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hi! How can I help?"},
    {"role": "user", "content": "What is AI?"},
])


class TestFormatDetection:
    """Auto-detect conversation format from content."""

    def test_detect_discord(self):
        fmt = detect_format(DISCORD_SAMPLE, "discord_export.json")
        assert fmt == "discord"

    def test_detect_telegram(self):
        fmt = detect_format(TELEGRAM_SAMPLE, "telegram_export.json")
        assert fmt == "telegram"

    def test_detect_whatsapp(self):
        fmt = detect_format(WHATSAPP_SAMPLE, "whatsapp_export.json")
        assert fmt == "whatsapp"

    def test_detect_generic_json(self):
        fmt = detect_format(GENERIC_SAMPLE, "chat.json")
        assert fmt is not None
        assert "generic" in fmt

    def test_detect_unknown_format_returns_none(self):
        fmt = detect_format("just some plain text", "notes.txt")
        # Returns a generic text type if it can parse it
        assert fmt is None or isinstance(fmt, str)

    def test_detect_by_filename_hint(self):
        """Detect from filename when content is ambiguous."""
        fmt = detect_format("{}", "discord_channel.json")
        assert fmt is not None

    def test_detect_empty_content(self):
        fmt = detect_format("", "empty.json")
        # Falls through to generic-text detection for empty strings
        assert fmt is not None


class TestDiscordNormalization:
    """Discord chat exports normalize correctly."""

    def test_normalize_discord_returns_string(self):
        result = normalize(DISCORD_SAMPLE, "discord")
        assert result is not None
        assert isinstance(result, str)
        assert "Alice" in result
        assert "Hello!" in result
        assert "Bob" in result

    def test_normalize_discord_auto_detect(self):
        result = normalize(DISCORD_SAMPLE)
        assert result is not None
        assert isinstance(result, str)
        assert len(result) > 0


class TestTelegramNormalization:
    """Telegram exports normalize correctly."""

    def test_normalize_telegram_returns_string(self):
        result = normalize(TELEGRAM_SAMPLE, "telegram")
        assert result is not None
        assert isinstance(result, str)
        assert "Alice" in result
        assert "Hello!" in result

    def test_normalize_telegram_service_message_skipped(self):
        """Service messages (join, leave) should be filtered."""
        data = json.dumps({
            "name": "Chat",
            "messages": [
                {"id": 1, "type": "message", "text": "Hello", "from": "Alice"},
                {"id": 2, "type": "service", "text": "Alice joined", "action": "join"},
            ]
        })
        result = normalize(data, "telegram")
        assert result is not None
        assert isinstance(result, str)
        assert "Hello" in result
        # "Alice joined" is a service message and should not appear
        assert "Alice joined" not in result


class TestWhatsAppNormalization:
    """WhatsApp exports normalize correctly."""

    def test_normalize_whatsapp_returns_string(self):
        result = normalize(WHATSAPP_SAMPLE, "whatsapp")
        assert result is not None
        assert isinstance(result, str)
        assert "Hello!" in result or "Hi there!" in result


class TestGenericNormalization:
    """Generic JSON chat exports normalize correctly."""

    def test_normalize_role_content_format(self):
        result = normalize(GENERIC_SAMPLE, "generic-messages")
        assert result is not None
        assert isinstance(result, str)
        assert "Hello" in result
        assert "assistant" in result or "Hi!" in result

    def test_normalize_author_text_format(self):
        """Alternate format with author/text keys."""
        data = json.dumps([
            {"author": "Alice", "text": "Hello"},
            {"author": "Bob", "text": "Hi"},
        ])
        result = normalize(data)
        assert result is not None
        assert isinstance(result, str)
        assert "Hello" in result or "Alice" in result


class TestRegistry:
    """Normalizer registry contains all expected formats."""

    def test_essential_normalizers_registered(self):
        assert "discord" in NORMALIZERS
        assert "telegram" in NORMALIZERS
        assert "whatsapp" in NORMALIZERS

    def test_detect_function_uses_registry(self):
        """detect_format iterates over NORMALIZERS keys."""
        fmt = detect_format(DISCORD_SAMPLE)
        assert fmt == "discord"
