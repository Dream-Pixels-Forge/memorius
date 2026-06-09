"""Memory verification and fact-checking.

Cross-reference agent statements against stored memories to detect
contradictions. If a stored memory says "project uses React" but the
agent says "project uses Vue" — flag it.
"""

from __future__ import annotations

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

    Checks for:
    1. Negation patterns (is/is not, use/don't use)
    2. Opposing pairs (yes/no, enable/disable)
    3. Entity-slot conflicts — same structure, different entity values
       e.g. "The project uses React" vs "The project uses Vue"
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

    # Entity-slot conflict detection:
    # If two sentences share the same template but differ in entity positions,
    # they likely contradict (e.g. "uses React" vs "uses Vue").
    words_a = text_a_lower.split()
    words_b = text_b_lower.split()

    if len(words_a) >= 3 and len(words_b) >= 3:
        # Find positions where words differ
        min_len = min(len(words_a), len(words_b))
        diff_positions = [
            i for i in range(min_len) if words_a[i] != words_b[i]
        ]

        # If most words match but a few differ (entity slots), it's a conflict
        match_ratio = (min_len - len(diff_positions)) / min_len
        if match_ratio >= 0.6 and 1 <= len(diff_positions) <= max(1, min_len // 3):
            # The differing words are potential entity-slot conflicts
            # Exclude common stop words from being counted as entity differences
            stop_words = {
                "the", "a", "an", "is", "are", "was", "were", "be", "been",
                "being", "have", "has", "had", "do", "does", "did", "will",
                "would", "could", "should", "may", "might", "can", "shall",
                "to", "of", "in", "for", "on", "with", "at", "by", "from",
                "as", "into", "about", "between", "through", "during", "before",
                "after", "above", "below", "and", "but", "or", "not", "no",
                "it", "its", "this", "that", "these", "those", "i", "we",
                "our", "my", "your", "their", "he", "she", "they", "you",
                "me", "him", "her", "us", "them",
            }
            entity_diffs = [
                i for i in diff_positions if words_a[i] not in stop_words
                                     and words_b[i] not in stop_words
            ]
            if entity_diffs:
                return True

    return False


def _text_similarity(text_a: str, text_b: str) -> float:
    """Text similarity using TF-IDF-like weighted word overlap.

    Words that are rarer (appear in fewer of the two texts) get higher weight,
    making the similarity more meaningful than plain Jaccard.
    """
    words_a = text_a.lower().split()
    words_b = text_b.lower().split()

    if not words_a or not words_b:
        return 0.0

    set_a = set(words_a)
    set_b = set(words_b)

    # Term frequency: how often each word appears in its source
    tf_a = {w: words_a.count(w) / len(words_a) for w in set_a}
    tf_b = {w: words_b.count(w) / len(words_b) for w in set_b}

    # Inverse document frequency: words appearing in both texts get lower weight
    all_words = set_a | set_b
    idf = {}
    for w in all_words:
        in_a = 1 if w in set_a else 0
        in_b = 1 if w in set_b else 0
        # IDF-like: rare in one text = higher weight
        idf[w] = 1.0 / (1.0 + in_a + in_b)

    # Weighted overlap
    intersection = set_a & set_b
    if not intersection:
        return 0.0

    weighted_sim = sum(tf_a.get(w, 0) * idf[w] + tf_b.get(w, 0) * idf[w]
                       for w in intersection)
    # Normalize by max possible (union)
    max_sim = sum(tf_a.get(w, 0) * idf[w] + tf_b.get(w, 0) * idf[w]
                   for w in all_words)

    return min(weighted_sim / max_sim, 1.0) if max_sim else 0.0


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
