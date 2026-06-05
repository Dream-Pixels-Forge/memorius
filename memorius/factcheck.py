"""Memory verification and fact-checking.

Cross-reference agent statements against stored memories to detect
contradictions. If a stored memory says "project uses React" but the
agent says "project uses Vue" — flag it.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("memorius.factcheck")


@dataclass
class FactCheckResult:
    """Result of a fact-check against stored memories."""
    statement: str
    verdict: str  # verified, contradicted, uncertain, no_match
    confidence: float  # 0.0 - 1.0
    vault: str | None = None
    matching_memories: list[dict[str, Any]] = field(default_factory=list)
    contradicting_memories: list[dict[str, Any]] = field(default_factory=list)
    explanation: str = ""


@dataclass
class Contradiction:
    """A detected contradiction between a statement and stored memory."""
    statement: str
    memory_content: str
    memory_id: str
    memory_metadata: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0


# ── Extraction patterns ──────────────────────────────────────────────────────

# Patterns that indicate factual claims
FACTUAL_PATTERNS = [
    re.compile(r"(?:the|this|our|my|that)\s+\w+\s+(?:is|are|was|were|uses?|has|have|does)\s+(.+)", re.I),
    re.compile(r"(?:we|i)\s+(?:use|prefer|chose|selected|decided)\s+(.+)", re.I),
    re.compile(r"(?:it|this)\s+(?:works?|runs?|functions?)\s+(?:by|with|using)\s+(.+)", re.I),
    re.compile(r"(?:the|a|an)\s+(\w+)\s+(?:version|release|update)\s+(?:is|was)\s+(.+)", re.I),
]


def extract_factual_claims(text: str) -> list[str]:
    """Extract factual claims from text that can be verified."""
    claims = []
    sentences = re.split(r'[.!?]+', text)

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 10:
            continue

        for pattern in FACTUAL_PATTERNS:
            match = pattern.search(sentence)
            if match:
                claims.append(sentence)
                break

    # Also include sentences with specific data
    data_patterns = [
        re.compile(r'\d{4}[-/]\d{2}[-/]\d{2}'),  # dates
        re.compile(r'v?\d+\.\d+[\.\d]*'),  # version numbers
        re.compile(r'https?://\S+'),  # URLs
        re.compile(r'/[\w/.-]+'),  # file paths
    ]

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 10:
            continue
        for pattern in data_patterns:
            if pattern.search(sentence):
                if sentence not in claims:
                    claims.append(sentence)
                break

    return claims


def check_statement(
    engine,
    statement: str,
    vault: str | None = None,
    similarity_threshold: float = 0.7,
) -> FactCheckResult:
    """Check a statement against stored memories.

    Args:
        engine: VaultEngine instance
        statement: The statement to verify
        vault: Filter by vault
        similarity_threshold: Minimum similarity to consider a match

    Returns:
        FactCheckResult with verdict and evidence
    """
    # Search for related memories
    results = engine.search(query=statement, vault=vault, limit=10)

    if not results:
        return FactCheckResult(
            statement=statement,
            verdict="no_match",
            confidence=0.0,
            explanation="No related memories found in vault",
        )

    matching = []
    contradicting = []

    for mem in results:
        content = mem.content or ""
        if not content:
            continue

        # Simple semantic similarity check
        sim = _text_similarity(statement, content)

        if sim >= similarity_threshold:
            # Check for contradiction
            is_contradiction = _detect_contradiction(statement, content)

            mem_info = {
                "id": mem.id,
                "content": content[:300],
                "vault": mem.vault,
                "shelf": mem.shelf,
                "metadata": mem.metadata,
            }

            if is_contradiction:
                contradicting.append(mem_info)
            else:
                matching.append(mem_info)

    # Determine verdict
    if contradicting:
        verdict = "contradicted"
        confidence = min(len(contradicting) * 0.3, 0.9)
        explanation = f"Found {len(contradicting)} contradicting memor{'y' if len(contradicting) == 1 else 'ies'}"
    elif matching:
        verdict = "verified"
        confidence = min(len(matching) * 0.25, 0.95)
        explanation = f"Found {len(matching)} supporting memor{'y' if len(matching) == 1 else 'ies'}"
    else:
        verdict = "uncertain"
        confidence = 0.3
        explanation = "Found related memories but none strongly match or contradict"

    return FactCheckResult(
        statement=statement,
        vault=vault,
        verdict=verdict,
        confidence=confidence,
        matching_memories=matching,
        contradicting_memories=contradicting,
        explanation=explanation,
    )


def _detect_contradiction(text_a: str, text_b: str) -> bool:
    """Detect if two texts contradict each other.

    Simple heuristic: check for negation patterns and opposing claims.
    """
    text_a_lower = text_a.lower()
    text_b_lower = text_b.lower()

    # Negation patterns
    negations = [
        ("is", "is not"), ("are", "are not"), ("was", "was not"),
        ("has", "has not"), ("does", "does not"), ("can", "can not"),
        ("will", "will not"), ("should", "should not"),
        ("use", "don't use"), ("prefer", "don't prefer"),
    ]

    for pos, neg in negations:
        if pos in text_a_lower and neg in text_b_lower:
            return True
        if neg in text_a_lower and pos in text_b_lower:
            return True

    # Check for opposing values
    opposing_pairs = [
        ("yes", "no"), ("true", "false"), ("enable", "disable"),
        ("add", "remove"), ("create", "delete"), ("start", "stop"),
        ("fast", "slow"), ("big", "small"), ("new", "old"),
    ]

    for a, b in opposing_pairs:
        if a in text_a_lower and b in text_b_lower:
            return True
        if b in text_a_lower and a in text_b_lower:
            return True

    return False


def _text_similarity(text_a: str, text_b: str) -> float:
    """Simple text similarity using word overlap (Jaccard)."""
    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())

    if not words_a or not words_b:
        return 0.0

    intersection = words_a & words_b
    union = words_a | words_b

    return len(intersection) / len(union) if union else 0.0


def batch_factcheck(
    engine,
    statements: list[str],
    vault: str | None = None,
) -> list[FactCheckResult]:
    """Check multiple statements at once."""
    return [
        check_statement(engine, stmt, vault=vault)
        for stmt in statements
    ]


def format_factcheck_report(results: list[FactCheckResult]) -> str:
    """Format fact-check results into a readable report."""
    lines = ["## Fact-Check Report\n"]

    for i, result in enumerate(results, 1):
        icon = {
            "verified": "✅",
            "contradicted": "❌",
            "uncertain": "⚠️",
            "no_match": "❓",
        }.get(result.verdict, "❓")

        lines.append(f"### {i}. {icon} {result.verdict.upper()}")
        lines.append(f"**Statement:** {result.statement}")
        lines.append(f"**Confidence:** {result.confidence:.0%}")
        lines.append(f"**Explanation:** {result.explanation}")

        if result.contradicting_memories:
            lines.append("\n**Contradicting memories:**")
            for mem in result.contradicting_memories:
                lines.append(f"- [{mem['vault']}/{mem['shelf']}] {mem['content'][:150]}")

        if result.matching_memories:
            lines.append("\n**Supporting memories:**")
            for mem in result.matching_memories:
                lines.append(f"- [{mem['vault']}/{mem['shelf']}] {mem['content'][:150]}")

        lines.append("")

    return "\n".join(lines)
