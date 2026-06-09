"""Tests for memorius/validation.py — input validation."""

import pytest
from memorius.validation import (
    validate_name,
    validate_content,
    MAX_NAME_LENGTH,
    MAX_CONTENT_LENGTH,
    MAX_FIELD_LENGTH,
    MAX_SEARCH_LIMIT,
    MAX_DIARY_CONTENT,
)


def test_validate_name_valid():
    """Valid names should pass."""
    assert validate_name("main", "vault") == "main"
    assert validate_name("my-vault_2", "vault") == "my-vault_2"
    assert validate_name("shelf-1", "shelf") == "shelf-1"


def test_validate_name_empty():
    """Empty names should raise ValueError."""
    with pytest.raises(ValueError, match="required"):
        validate_name("", "vault")
    with pytest.raises(ValueError, match="required"):
        validate_name("   ", "vault")


def test_validate_name_too_long():
    """Names exceeding MAX_NAME_LENGTH should raise ValueError."""
    long_name = "a" * (MAX_NAME_LENGTH + 1)
    with pytest.raises(ValueError, match="too long"):
        validate_name(long_name, "vault")


def test_validate_name_invalid_chars():
    """Names with invalid characters should raise ValueError."""
    with pytest.raises(ValueError, match="letters, numbers"):
        validate_name("my vault", "vault")  # space
    with pytest.raises(ValueError, match="letters, numbers"):
        validate_name("vault/sub", "vault")  # slash
    with pytest.raises(ValueError, match="letters, numbers"):
        validate_name("vault..", "vault")  # dots


def test_validate_name_strips_whitespace():
    """Leading/trailing whitespace should be stripped."""
    assert validate_name("  main  ", "vault") == "main"


def test_validate_content_valid():
    """Valid content should pass."""
    assert validate_content("hello world") == "hello world"


def test_validate_content_empty():
    """Empty content should raise ValueError."""
    with pytest.raises(ValueError, match="empty"):
        validate_content("")
    with pytest.raises(ValueError, match="empty"):
        validate_content("   ")


def test_validate_content_too_long():
    """Content exceeding MAX_CONTENT_LENGTH should raise ValueError."""
    long_content = "a" * (MAX_CONTENT_LENGTH + 1)
    with pytest.raises(ValueError, match="too long"):
        validate_content(long_content)


def test_validate_content_not_string():
    """Non-string content should raise ValueError."""
    with pytest.raises(ValueError, match="string"):
        validate_content(123)
