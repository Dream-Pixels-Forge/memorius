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


def test_vault_starts_daemon_when_enabled():
    """VaultEngine should start consolidation daemon when enabled."""
    from memorius.vault import VaultEngine
    cfg = get_config()
    cfg["consolidation"]["enabled"] = True
    vault = VaultEngine(config=cfg)
    assert hasattr(vault, '_consolidation_daemon')
    assert vault._consolidation_daemon is not None
    vault._consolidation_daemon.stop()
    vault._consolidation_daemon.join(timeout=2)


def test_vault_no_daemon_when_disabled():
    """VaultEngine should not start consolidation daemon when disabled."""
    from memorius.vault import VaultEngine
    cfg = get_config()
    cfg["consolidation"]["enabled"] = False
    vault = VaultEngine(config=cfg)
    assert hasattr(vault, '_consolidation_daemon')
    assert vault._consolidation_daemon is None
