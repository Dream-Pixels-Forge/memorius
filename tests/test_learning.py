"""Tests for Learning module — store, recall, and manage agent learnings."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def engine():
    """Create a VaultEngine with isolated temp stores."""
    tmp = Path(tempfile.mkdtemp())
    os.environ["MEMORIUS_STORAGE_PATH"] = str(tmp)
    from memorius.config import load_config
    from memorius.vault import VaultEngine

    config = load_config()
    eng = VaultEngine(config)
    yield eng
    eng.close()
    shutil.rmtree(tmp, ignore_errors=True)


def test_store_learning_basic(engine):
    """Storing a learning should return a memory with correct metadata."""
    mem = engine.store_learning(
        content="Use pytest fixtures for test isolation",
        category="strategy",
        context="Writing tests for memorius",
        solution="Create temp directories and clean up after",
        tags=["testing", "pytest"],
        confidence=0.95,
    )

    assert mem.id
    assert mem.content == "Use pytest fixtures for test isolation"
    assert mem.shelf == "learnings"
    assert mem.folder == "strategy"
    assert mem.metadata.get("category") == "strategy"
    assert mem.metadata.get("context") == "Writing tests for memorius"
    assert mem.metadata.get("solution") == "Create temp directories and clean up after"
    assert mem.metadata.get("tags") == ["testing", "pytest"]
    assert mem.metadata.get("confidence") == 0.95
    assert mem.metadata.get("learning") is True
    assert mem.metadata.get("applied_count") == 0


def test_store_learning_all_categories(engine):
    """All valid categories should be accepted."""
    categories = [
        "bug_fix", "strategy", "pattern", "self_improvement",
        "tool_usage", "code_snippet", "workflow"
    ]

    for cat in categories:
        mem = engine.store_learning(
            content=f"Learning about {cat}",
            category=cat,
        )
        assert mem.metadata.get("category") == cat
        assert mem.folder == cat


def test_store_learning_invalid_category(engine):
    """Invalid category should raise ValueError."""
    with pytest.raises(ValueError, match="Invalid category"):
        engine.store_learning(
            content="This should fail",
            category="invalid_category",
        )


def test_recall_learnings(engine):
    """Recall should find learnings by semantic similarity."""
    engine.store_learning(
        content="Use parameterized queries to prevent SQL injection",
        category="bug_fix",
        context="Security vulnerability found",
        solution="Always use ? placeholders",
    )
    engine.store_learning(
        content="Cache expensive computations with lru_cache",
        category="strategy",
        context="Slow function calls",
    )

    results = engine.recall_learnings(query="SQL injection prevention")
    assert len(results) >= 1
    assert any("SQL injection" in m.content for m in results)


def test_recall_learnings_by_category(engine):
    """Recall with category filter should only return matching category."""
    engine.store_learning(
        content="Fix null pointer in login handler",
        category="bug_fix",
    )
    engine.store_learning(
        content="Use connection pooling for database",
        category="strategy",
    )

    bug_fixes = engine.recall_learnings(
        query="database",
        category="bug_fix",
    )
    assert all(m.metadata.get("category") == "bug_fix" for m in bug_fixes)


def test_list_learnings(engine):
    """List learnings should return all learnings with stats."""
    engine.store_learning(
        content="Learning 1",
        category="bug_fix",
    )
    engine.store_learning(
        content="Learning 2",
        category="strategy",
    )

    result = engine.list_learnings()
    assert result["summary"]["total"] == 2
    assert result["summary"]["by_category"]["bug_fix"] == 1
    assert result["summary"]["by_category"]["strategy"] == 1


def test_apply_learning(engine):
    """Applying a learning should increment its counter."""
    mem = engine.store_learning(
        content="Test learning",
        category="strategy",
    )

    updated = engine.apply_learning(mem.id)
    assert updated is not None
    assert updated.metadata.get("applied_count") == 1
    assert updated.metadata.get("last_applied") is not None

    # Apply again
    updated2 = engine.apply_learning(mem.id)
    assert updated2.metadata.get("applied_count") == 2


def test_apply_learning_not_found(engine):
    """Applying a non-existent learning should return None."""
    result = engine.apply_learning("00000000-0000-0000-0000-000000000000")
    assert result is None


def test_learning_stats(engine):
    """Learning stats should return correct counts."""
    engine.store_learning(
        content="Bug fix 1",
        category="bug_fix",
        confidence=0.9,
    )
    engine.store_learning(
        content="Strategy 1",
        category="strategy",
        confidence=0.8,
    )

    stats = engine.get_learning_stats()
    assert stats["total"] == 2
    assert stats["by_category"]["bug_fix"] == 1
    assert stats["by_category"]["strategy"] == 1
    assert 0.8 <= stats["avg_confidence"] <= 0.9
    assert stats["total_applied"] == 0


def test_learning_confidence_clamped(engine):
    """Confidence should be clamped to 0-1 range."""
    mem = engine.store_learning(
        content="Test",
        category="strategy",
        confidence=1.5,  # Over max
    )
    assert mem.metadata.get("confidence") == 1.0

    mem2 = engine.store_learning(
        content="Test 2",
        category="strategy",
        confidence=-0.5,  # Under min
    )
    assert mem2.metadata.get("confidence") == 0.0


def test_learning_with_context_and_solution(engine):
    """Context and solution should be stored in metadata."""
    mem = engine.store_learning(
        content="Fix CORS headers",
        category="bug_fix",
        context="API requests failing from frontend",
        solution="Add Access-Control-Allow-Origin header",
    )

    assert mem.metadata.get("context") == "API requests failing from frontend"
    assert mem.metadata.get("solution") == "Add Access-Control-Allow-Origin header"
