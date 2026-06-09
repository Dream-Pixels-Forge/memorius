"""LLM-powered memory extraction from conversations.

Replaces the dumb ``\\n{2,}`` split in ``mine()`` with structured extraction
that identifies: key decisions, user preferences, technical facts,
action items, and relationships.

Supports multiple backends:
  - OpenAI API (if openai package installed)
  - Local Ollama (if running)
  - Fallback: regex-based extraction (no LLM required)
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("memorius.llm_extract")

# Input validation constants
MAX_CONVERSATION_LENGTH = 50_000
MAX_MEMORY_CONTENT_LENGTH = 1_000
VALID_CATEGORIES = {"decision", "preference", "fact", "action_item", "relationship", "context"}


@dataclass
class ExtractedMemory:
    """A structured memory extracted from a conversation."""
    content: str
    category: str  # decision, preference, fact, action_item, relationship, context
    confidence: float  # 0.0 - 1.0
    topics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _sanitize_conversation(conversation: str) -> str:
    """Sanitize conversation text before sending to LLM.

    Strips prompt injection attempts while preserving legitimate content.
    """
    if not conversation:
        return ""

    # Truncate to prevent token overflow
    conversation = conversation[:MAX_CONVERSATION_LENGTH]

    # Remove common injection patterns that try to manipulate the extraction
    injection_patterns = [
        re.compile(r'(?i)ignore\s+(?:all\s+)?previous\s+instructions'),
        re.compile(r'(?i)disregard\s+(?:all\s+)?previous'),
        re.compile(r'(?i)you\s+are\s+now\s+'),
        re.compile(r'(?i)new\s+instructions?:'),
        re.compile(r'(?i)system\s*prompt:'),
        re.compile(r'(?i)override\s+instructions'),
    ]

    sanitized = conversation
    for pattern in injection_patterns:
        sanitized = pattern.sub("[content]", sanitized)

    return sanitized


def _validate_extracted_memory(memory: dict) -> ExtractedMemory | None:
    """Validate and sanitize an extracted memory before storage.

    Returns None if the memory is invalid or suspicious.
    """
    content = memory.get("content", "")
    if not content or not isinstance(content, str):
        return None

    # Sanitize content
    content = content.strip()[:MAX_MEMORY_CONTENT_LENGTH]

    # Validate category
    category = memory.get("category", "context")
    if category not in VALID_CATEGORIES:
        category = "context"

    # Validate confidence
    try:
        confidence = float(memory.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))
    except (ValueError, TypeError):
        confidence = 0.5

    # Validate topics
    topics = memory.get("topics", [])
    if not isinstance(topics, list):
        topics = []
    topics = [str(t)[:50] for t in topics[:10]]  # Limit topic count and length

    return ExtractedMemory(
        content=content,
        category=category,
        confidence=confidence,
        topics=topics,
    )


# ── Extraction prompts ────────────────────────────────────────────────────────

EXTRACTION_PROMPT = """Extract key memories from this conversation. Return a JSON array of memories.

For each memory, provide:
- content: The key information (concise, self-contained)
- category: One of: decision, preference, fact, action_item, relationship, context
- confidence: 0.0-1.0 (how confident are you this is important)
- topics: List of related topics/tags

Categories:
- decision: Something decided or agreed upon
- preference: User preference or style choice
- fact: Technical fact, dates, names, code details
- action_item: Something that needs to be done
- relationship: Connection between people, projects, concepts
- context: Background information that might be useful later

Return ONLY the JSON array, no explanation.

Conversation:
{conversation}

JSON:"""


# ── LLM backends ──────────────────────────────────────────────────────────────


def _extract_with_openai(conversation: str, model: str = "gpt-4o-mini") -> list[ExtractedMemory]:
    """Extract memories using OpenAI API."""
    try:
        from openai import OpenAI
        client = OpenAI()

        # Sanitize conversation before sending to LLM
        sanitized = _sanitize_conversation(conversation)
        prompt = EXTRACTION_PROMPT.format(conversation=sanitized[:4000])
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        content = resp.choices[0].message.content
        data = json.loads(content)
        memories = data if isinstance(data, list) else data.get("memories", [])

        validated = []
        for m in memories:
            if m.get("content"):
                validated_mem = _validate_extracted_memory(m)
                if validated_mem:
                    validated.append(validated_mem)
        return validated
    except Exception as e:
        logger.warning(f"OpenAI extraction failed: {e}")
        return []


def _extract_with_ollama(conversation: str, model: str = "llama3.2") -> list[ExtractedMemory]:
    """Extract memories using local Ollama."""
    try:
        import httpx
        # Sanitize conversation before sending to LLM
        sanitized = _sanitize_conversation(conversation)
        prompt = EXTRACTION_PROMPT.format(conversation=sanitized[:4000])
        resp = httpx.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=60,
        )
        content = resp.json().get("response", "")
        # Extract JSON from response
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            memories = json.loads(match.group())
            validated = []
            for m in memories:
                if m.get("content"):
                    validated_mem = _validate_extracted_memory(m)
                    if validated_mem:
                        validated.append(validated_mem)
            return validated
    except Exception as e:
        logger.warning(f"Ollama extraction failed: {e}")
    return []


def _extract_with_regex(conversation: str) -> list[ExtractedMemory]:
    """Fallback: regex-based extraction (no LLM required)."""
    memories = []
    lines = conversation.strip().split("\n")

    # Pattern: "I prefer X", "I like X", "I want X"
    preference_pattern = re.compile(
        r"(?:i (?:prefer|like|want|need|love|hate|use))\s+(.+)",
        re.IGNORECASE,
    )

    # Pattern: "Let's do X", "We should X", "Decision: X"
    decision_pattern = re.compile(
        r"(?:let'?s (?:do|use|go|try|make)|we should|decision:?|agree[d]? (?:to|on))\s+(.+)",
        re.IGNORECASE,
    )

    # Pattern: "TODO:", "FIXME:", "Action:", "Remember to"
    action_pattern = re.compile(
        r"(?:todo|fixme|action|remember to|don'?t forget|need to)\s*[:\-]?\s*(.+)",
        re.IGNORECASE,
    )

    # Pattern: URLs, file paths, function names
    technical_pattern = re.compile(
        r"((?:https?://\S+|/[\w/.-]+|\b[\w]+(?:\(\)|\.[\w()]+)))",
    )

    for line in lines:
        line = line.strip()
        if not line:
            continue

        m = preference_pattern.search(line)
        if m:
            memories.append(ExtractedMemory(
                content=f"User preference: {m.group(0).strip()}",
                category="preference",
                confidence=0.6,
            ))
            continue

        m = decision_pattern.search(line)
        if m:
            memories.append(ExtractedMemory(
                content=f"Decision: {m.group(0).strip()}",
                category="decision",
                confidence=0.6,
            ))
            continue

        m = action_pattern.search(line)
        if m:
            memories.append(ExtractedMemory(
                content=f"Action item: {m.group(0).strip()}",
                category="action_item",
                confidence=0.5,
            ))
            continue

        # Technical facts
        tech_matches = technical_pattern.findall(line)
        if tech_matches and len(line) > 20:
            memories.append(ExtractedMemory(
                content=line[:500],
                category="fact",
                confidence=0.4,
                topics=tech_matches[:3],
            ))

    return memories


# ── Public API ────────────────────────────────────────────────────────────────


def extract_memories(
    conversation: str,
    backend: str = "auto",
    model: str | None = None,
) -> list[ExtractedMemory]:
    """Extract structured memories from a conversation.

    Args:
        conversation: The conversation text
        backend: "openai", "ollama", "regex", or "auto" (try all)
        model: Model name for the backend

    Returns:
        List of ExtractedMemory objects
    """
    if not conversation.strip():
        return []

    if backend == "openai":
        return _extract_with_openai(conversation, model or "gpt-4o-mini")
    elif backend == "ollama":
        return _extract_with_ollama(conversation, model or "llama3.2")
    elif backend == "regex":
        return _extract_with_regex(conversation)

    # Auto: try backends in order
    # 1. Try OpenAI if available
    try:
        from openai import OpenAI
        results = _extract_with_openai(conversation, model or "gpt-4o-mini")
        if results:
            return results
    except ImportError:
        pass

    # 2. Try Ollama if available
    try:
        import httpx
        ollama_available = False
        for attempt in range(3):
            try:
                resp = httpx.get("http://localhost:11434/api/tags", timeout=3)
                if resp.status_code == 200:
                    ollama_available = True
                    break
            except Exception:
                if attempt < 2:
                    import time
                    time.sleep(0.5 * (attempt + 1))
        if ollama_available:
            results = _extract_with_ollama(conversation, model or "llama3.2")
            if results:
                return results
    except Exception:
        pass

    # 3. Fallback to regex
    return _extract_with_regex(conversation)


def format_for_storage(
    memories: list[ExtractedMemory],
) -> list[dict[str, Any]]:
    """Format extracted memories for storage in the vault."""
    return [
        {
            "content": m.content,
            "metadata": {
                "category": m.category,
                "confidence": m.confidence,
                "topics": m.topics,
                "extraction_method": "llm",
                **m.metadata,
            },
        }
        for m in memories
    ]
