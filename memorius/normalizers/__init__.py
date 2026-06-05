"""
Additional conversation format normalizers for Memorius.

Extends the formats already supported for Memorius (Claude Code,
ChatGPT, Slack, Gemini, Codex) with Discord, Telegram, WhatsApp, and
generic formats.

Usage:
  memorius-normalize detect file.json       # auto-detect format
  memorius-normalize convert file.json       # convert to Memorius transcript
  memorius-normalize convert file.json --format discord
  memorius-normalize batch ./chat-exports/   # batch convert a directory
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("memorius.normalizers")

# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def detect_format(content: str, filename: str = "") -> str | None:
    """Auto-detect the conversation format from content + filename.

    Returns the format name (e.g. 'discord', 'telegram') or None if unknown.
    """
    # Check by filename first
    name_lower = filename.lower()

    # Discord exports
    if "discord" in name_lower and (name_lower.endswith(".json") or name_lower.endswith(".csv")):
        return "discord"

    # Telegram exports
    if "telegram" in name_lower or "result" in name_lower and name_lower.endswith(".json"):
        return "telegram"

    # WhatsApp exports
    if "whatsapp" in name_lower or name_lower.endswith(".txt") and "whatsapp" in name_lower:
        return "whatsapp"

    # Try content-based detection
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        # Plain text — could be WhatsApp or generic
        return detect_text_format(content)

    if isinstance(data, dict):
        # Discord channel JSON
        if "messages" in data and any("author" in m for m in data["messages"][:3]):
            return "discord"
        # Telegram chat export
        if "messages" in data and any("from" in m for m in data["messages"][:3]) and "text" in data["messages"][0]:
            return "telegram"
        # Generic chat format
        if "conversations" in data or "chats" in data:
            return "generic-chat"

    if isinstance(data, list):
        # Could be a list of messages
        if data and isinstance(data[0], dict):
            if "role" in data[0] or "author" in data[0]:
                return "generic-messages"
            if "from" in data[0] and "text" in data[0]:
                return "telegram"

    return None


def detect_text_format(content: str) -> str | None:
    """Detect format from plain text content."""
    lines = content.strip().split("\n")

    # WhatsApp format: [date, time] Person: message
    whatsapp_pattern = re.compile(r"^\[\d{1,2}[/-]\d{1,2}[/-]\d{2,4}.+?\].+?:", re.MULTILINE)
    whatsapp_matches = sum(1 for _ in whatsapp_pattern.finditer(content[:5000]))
    if whatsapp_matches >= 3:
        return "whatsapp"

    # WhatsApp alternative: date - Person: message
    alt_whatsapp = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}.+?\- .+?:", re.MULTILINE)
    alt_matches = sum(1 for _ in alt_whatsapp.finditer(content[:5000]))
    if alt_matches >= 3:
        return "whatsapp"

    return "generic-text"


# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def normalize_discord(content: str, channel_name: str = "discord-chat") -> str:
    """Convert a Discord channel export JSON to Memorius transcript format.

    Discord export format (from DiscordChatExporter or similar):
    {
      "messages": [
        {
          "id": "...",
          "type": "Default",
          "timestamp": "2024-01-01T12:00:00+00:00",
          "content": "Hello!",
          "author": { "id": "...", "name": "Alice", "nickname": "Ali" }
        },
        ...
      ]
    }
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return f"[error: invalid Discord JSON — {e}]"

    messages = data.get("messages", data if isinstance(data, list) else [])
    if not isinstance(messages, list):
        # Try the data itself as a list
        if isinstance(data, list):
            messages = data
        else:
            return "[error: no messages found in Discord export]"

    transcript_lines = [f"# Discord Channel: {channel_name}"]
    transcript_lines.append(f"# Messages: {len(messages)}")
    transcript_lines.append("")

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        author = msg.get("author", {})
        if isinstance(author, dict):
            name = author.get("nickname") or author.get("name") or author.get("username", "Unknown")
        else:
            name = str(author)
        text = msg.get("content", "")
        timestamp = msg.get("timestamp", "")
        if timestamp:
            timestamp = timestamp[:19]  # strip timezone for readability

        if text:
            transcript_lines.append(f"> **{name}** [{timestamp}]")
            transcript_lines.append(f"> {text}")
            transcript_lines.append("")

    if len(transcript_lines) <= 4:
        return "[error: no messages with content found in Discord export]"

    return "\n".join(transcript_lines)


def normalize_telegram(content: str, chat_title: str = "telegram-chat") -> str:
    """Convert a Telegram chat export JSON to Memorius transcript format.

    Telegram export format (from Telegram Desktop export):
    {
      "name": "Chat Name",
      "type": "personal_chat" | "private_group" | "private_supergroup",
      "messages": [
        {
          "id": 123,
          "type": "message",
          "date": "2024-01-01T12:00:00",
          "from": "Alice",
          "from_id": "user123456",
          "text": "Hello everyone!"
        },
        ...
      ]
    }
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return f"[error: invalid Telegram JSON — {e}]"

    chat_name = data.get("name", chat_title)
    messages = data.get("messages", [])

    transcript_lines = [f"# Telegram Chat: {chat_name}"]
    transcript_lines.append(f"# Messages: {len(messages)}")
    transcript_lines.append("")

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("type") == "service":
            continue  # skip join/leave notifications

        author = msg.get("from", msg.get("actor", "Unknown"))
        text = msg.get("text", "")
        date = msg.get("date", "")

        # Telegram sometimes returns text as a list of mixed strings and objects
        if isinstance(text, list):
            parts = []
            for part in text:
                if isinstance(part, str):
                    parts.append(part)
                elif isinstance(part, dict):
                    parts.append(part.get("text", ""))
            text = "".join(parts)
        elif not isinstance(text, str):
            text = str(text)

        # Handle forwarded messages
        forwarded = msg.get("forwarded_from", "")
        if forwarded:
            text = f"[Forwarded from {forwarded}] {text}"

        if text and text.strip():
            transcript_lines.append(f"> **{author}** [{date[:19]}]")
            transcript_lines.append(f"> {text.strip()}")
            transcript_lines.append("")

    if len(transcript_lines) <= 4:
        return "[error: no messages with content found in Telegram export]"

    return "\n".join(transcript_lines)


def normalize_whatsapp(content: str, chat_name: str = "whatsapp-chat") -> str:
    """Convert a WhatsApp chat export (plain text) to Memorius transcript format.

    WhatsApp export format (two variants):

    Variant 1 (international):
      [1/15/24, 12:00:00 PM] Alice: Hello!

    Variant 2 (US/EU):
      1/15/24, 12:00 PM - Alice: Hello!
    """
    lines = content.strip().split("\n")

    transcript_lines = [f"# WhatsApp Chat: {chat_name}"]
    transcript_lines.append(f"# Messages: {len(lines)}")
    transcript_lines.append("")

    # Try multiple WhatsApp patterns
    # Variant 1: [1/15/24, 12:00:00 PM] Alice: Hello!
    # Variant 2: 1/15/24, 12:00 PM - Alice: Hello!
    pattern = re.compile(
        r"^\s*"
        r"\[?"
        r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4},?\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp][Mm])?)"
        r"\]?"
        r"(?:\s+-\s+|\]\s+)"
        r"([^\n:]+?):\s*"
        r"(.*)$"
    )

    parsed_count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip system messages
        if "Messages and calls are end-to-end encrypted" in line:
            continue
        # System messages are anything that doesn't begin with a date
        # (i.e. fails the chat-message pattern). WhatsApp system notices
        # come in three shapes — "[date] author joined", "date - author
        # joined", and bare "author joined" — and none of them have a
        # `:` separator, so we detect them by absence of the date prefix.
        if not re.match(r"^\s*\[?\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", line):
            transcript_lines.append(f"> *{line}*")
            transcript_lines.append("")
            continue

        match = pattern.match(line)
        if match:
            timestamp = match.group(1).strip()
            author = match.group(2).strip()
            text = match.group(3).strip()
            if text and not text.startswith("<Media omitted>"):
                transcript_lines.append(f"> **{author}** [{timestamp}]")
                transcript_lines.append(f"> {text}")
                transcript_lines.append("")
                parsed_count += 1

    if parsed_count == 0:
        # Fallback: try naive split on first colon
        transcript_lines.append("[warning: could not parse WhatsApp format, using raw lines]")
        transcript_lines.append("")
        for line in lines:
            line = line.strip()
            if line and ":" in line:
                idx = line.index(":")
                author = line[:idx].strip()
                text = line[idx+1:].strip()
                transcript_lines.append(f"> **{author}**")
                transcript_lines.append(f"> {text}")
                transcript_lines.append("")

    if len(transcript_lines) <= 4:
        return "[error: no parsable WhatsApp messages found]"

    return "\n".join(transcript_lines)


def normalize_generic_json(content: str, source_name: str = "chat-export") -> str:
    """Try to normalize any JSON chat format into Memorius transcript.

    Handles formats like:
    - List of {role, content} objects (OpenAI-style)
    - List of {author, text} objects (generic)
    - Dict with conversations/chats key
    """
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return f"[error: invalid JSON — {e}]"

    transcript_lines = [f"# Chat Export: {source_name}"]
    transcript_lines.append("")

    messages = []

    if isinstance(data, list):
        messages = data
    elif isinstance(data, dict):
        # Try common keys
        for key in ("messages", "conversations", "chats", "history", "log"):
            if key in data:
                val = data[key]
                if isinstance(val, list):
                    messages = val
                    break
                elif isinstance(val, dict):
                    # Some formats nest messages inside conversation objects
                    for conv_key, conv_val in val.items():
                        if isinstance(conv_val, list):
                            messages = conv_val
                            break
                    if messages:
                        break

    if not messages:
        # Try to find any list in the data
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, list) and len(val) > 1 and isinstance(val[0], dict):
                    messages = val
                    break

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        # Try common field names for author/role
        author = (
            msg.get("author") or msg.get("from") or msg.get("role") or msg.get("speaker") or msg.get("name") or "Unknown"
        )
        # Try common field names for content/text
        text = msg.get("content") or msg.get("text") or msg.get("message") or msg.get("body") or ""
        timestamp = msg.get("timestamp") or msg.get("time") or msg.get("date") or ""

        if isinstance(text, list):
            text = " ".join(str(t) if isinstance(t, str) else t.get("text", "") for t in text)
        elif not isinstance(text, str):
            text = str(text) if text is not None else ""

        if isinstance(author, dict):
            author = author.get("name") or author.get("username") or str(author.get("id", ""))

        if text and text.strip():
            ts_part = f" [{timestamp[:19]}]" if timestamp else ""
            transcript_lines.append(f"> **{author}**{ts_part}")
            transcript_lines.append(f"> {text.strip()}")
            transcript_lines.append("")

    if len(transcript_lines) <= 4:
        return "[error: could not extract messages from generic JSON]"

    return "\n".join(transcript_lines)


def normalize_plain_text(content: str, source_name: str = "chat-transcript") -> str:
    """Normalize plain text as a basic transcript.

    Uses heuristic: lines starting with ">" are treated as existing transcript.
    Lines with ":" are treated as speaker: message pairs.
    Everything else is treated as narrative text.
    """
    lines = content.strip().split("\n")
    transcript_lines = [f"# Plain Text: {source_name}"]

    # Detect if already has > markers (already a transcript)
    has_markers = any(line.strip().startswith(">") for line in lines[:20])

    if has_markers:
        # Already transcript format — pass through with header
        transcript_lines.append("")
        transcript_lines.append(content)
        return "\n".join(transcript_lines)

    transcript_lines.append("")
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if ":" in line and len(line.split(":", 1)[0]) < 30:
            # Likely a speaker line
            transcript_lines.append(f"> {line}")
        else:
            transcript_lines.append(f"> {line}")

    return "\n".join(transcript_lines)


# ---------------------------------------------------------------------------
# Normalizer dispatch
# ---------------------------------------------------------------------------

NORMALIZERS = {
    "discord": normalize_discord,
    "telegram": normalize_telegram,
    "whatsapp": normalize_whatsapp,
    "generic-json": normalize_generic_json,
    "generic-messages": normalize_generic_json,
    "generic-chat": normalize_generic_json,
    "generic-text": normalize_plain_text,
}


def normalize(content: str, filename: str = "", format: str | None = None) -> str:
    """Auto-detect and normalize any conversation format."""
    if not format:
        format = detect_format(content, filename)

    if not format or format not in NORMALIZERS:
        # Try generic JSON
        try:
            json.loads(content)
            format = "generic-json"
        except (json.JSONDecodeError, ValueError):
            format = "generic-text"

    normalizer = NORMALIZERS.get(format, normalize_plain_text)
    return normalizer(content, filename)


def normalize_file(path: str | Path, output_dir: str | Path | None = None) -> str | None:
    """Normalize a single file and optionally write to output directory."""
    path = Path(path)
    content = path.read_text(encoding="utf-8", errors="replace")

    result = normalize(content, path.name)

    if output_dir:
        output_path = Path(output_dir) / f"{path.stem}-transcript{path.suffix}"
        if output_path.suffix not in (".txt", ".md", ".json", ".jsonl"):
            output_path = output_path.with_suffix(".txt")
        output_path.write_text(result)
        logger.info(f"Written: {output_path}")
        return str(output_path)

    return result
