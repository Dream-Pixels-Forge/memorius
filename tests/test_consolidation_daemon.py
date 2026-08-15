"""Tests for auto-consolidation daemon (v0.8.0)."""
import sqlite3
from memorius.consolidation import ConsolidationDaemon
from memorius.config import get_config


def test_config_has_consolidation_section():
    """Config should include consolidation settings."""
    cfg = get_config()
    cons = cfg.get("consolidation", {})
    assert "enabled" in cons
    assert cons["enabled"] is False


def test_daemon_stops():
    """ConsolidationDaemon should start and stop cleanly."""
    daemon = ConsolidationDaemon(
        meta_store=sqlite3.connect(":memory:"),
        vector_store=None,
        config=get_config(),
    )
    daemon.start()
    assert daemon.is_alive()
    daemon.stop()
    daemon.join(timeout=2)
    assert not daemon.is_alive()
