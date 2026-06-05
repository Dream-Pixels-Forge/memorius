"""Regression tests for v0.1.3 polish round.

Each test guards a specific bug found in the v0.1.2 review. They live
together so future cleanup passes can run them as a single suite.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


# ────────────────────────────────────────────────────────────────────
# 1. MCP and REST servers report the real __version__, not a hardcoded
#    literal that drifts behind.
# ────────────────────────────────────────────────────────────────────
def test_mcp_server_version_reflects_package():
    """mcp_server.py should import __version__ rather than hardcode "0.1.0"."""
    from memorius import __version__
    from memorius.mcp_server import _memorius_version
    assert _memorius_version == __version__


def test_rest_server_version_reflects_package():
    """rest_server.py should import __version__ rather than hardcode "0.1.0"."""
    from memorius import __version__
    import memorius.rest_server as rest
    assert rest._memorius_version == __version__


# ────────────────────────────────────────────────────────────────────
# 2. PiAdapter.can_parse must accept every event its parse() handles.
#    In v0.1.2 it only accepted 5 of the 8 events in event_type_map,
#    so payloads with event="stop" or "shutdown" fell through to
#    GenericAgentAdapter.
# ────────────────────────────────────────────────────────────────────
def test_pi_adapter_can_parse_advertises_all_events():
    from memorius.hooks import PiAdapter

    advertised = set(PiAdapter.event_type_map.keys())
    for ev in advertised:
        payload = {"session_id": "abc", "event": ev}
        assert PiAdapter.can_parse(payload), (
            f"PiAdapter advertises event_type_map[{ev!r}] but can_parse "
            f"rejects it — payloads with this event fall through to "
            f"GenericAgentAdapter."
        )


# ────────────────────────────────────────────────────────────────────
# 3. conditional_diary used to crash on the default config because
#    interval_exchanges: "{save_interval}" stayed a literal string and
#    int("{save_interval}") raised ValueError. The fix substitutes
#    {save_interval} at config-load time.
# ────────────────────────────────────────────────────────────────────
def test_default_config_substitutes_save_interval():
    from memorius.hooks.engine import HookConfig

    cfg = HookConfig.default()
    for action in cfg.actions.get("session_stop", []):
        if action.type == "conditional_diary":
            interval = action.config.get("interval_exchanges")
            # Must be coercible to int without raising.
            assert int(interval) == cfg.save_interval


def test_template_substitution_recursive():
    from memorius.hooks.engine import _substitute_templates

    data = {
        "a": "x is {save_interval}",
        "b": ["list {save_interval}", {"nested": "{save_interval}!"}],
        "c": 42,  # non-strings untouched
    }
    out = _substitute_templates(data, {"save_interval": "15"})
    assert out["a"] == "x is 15"
    assert out["b"][0] == "list 15"
    assert out["b"][1]["nested"] == "15!"
    assert out["c"] == 42


# ────────────────────────────────────────────────────────────────────
# 4. save_checkpoint used to persist int(time.time()) under the
#    "exchange_count" key, making should_save's interval check
#    meaningless. It should now persist a real exchange count.
# ────────────────────────────────────────────────────────────────────
def test_save_checkpoint_uses_real_exchange_count():
    from memorius.hooks import HookEvent, HookEventType
    from memorius.hooks.engine import HookConfig, HookEngine, HookStateManager

    cfg = HookConfig.default()
    with tempfile.TemporaryDirectory() as td:
        sm = HookStateManager(Path(td) / "state")
        eng = HookEngine.__new__(HookEngine)
        eng.config = cfg
        eng.state_manager = sm
        eng._last_event_time = {}
        eng._engine = None

        ev = HookEvent(
            event_type=HookEventType.SESSION_STOP,
            session_id="regression-1",
            transcript_path=None,
            agent_name="test",
            raw_payload={"session_id": "regression-1", "event": "stop",
                         "exchange_count": 42},
            can_block=False,
        )
        count = eng._resolve_exchange_count(ev)
        sm.save_checkpoint(ev.session_id, count)

        state = json.loads((Path(td) / "state" / "regression-1_state.json").read_text())
        assert state["exchange_count"] == 42
        # Not a timestamp:
        assert state["exchange_count"] < 1_000_000_000


def test_save_checkpoint_counts_events_when_agent_omits_exchange_count():
    """Agents that don't report exchange_count get a per-session counter."""
    from memorius.hooks import HookEvent, HookEventType
    from memorius.hooks.engine import HookConfig, HookEngine, HookStateManager

    cfg = HookConfig.default()
    with tempfile.TemporaryDirectory() as td:
        sm = HookStateManager(Path(td) / "state")
        eng = HookEngine.__new__(HookEngine)
        eng.config = cfg
        eng.state_manager = sm
        eng._last_event_time = {}
        eng._engine = None

        for i in range(3):
            ev = HookEvent(
                event_type=HookEventType.SESSION_STOP,
                session_id="counter-session",
                transcript_path=None,
                agent_name="test",
                raw_payload={"session_id": "counter-session", "event": "stop"},
                can_block=False,
            )
            count = eng._resolve_exchange_count(ev)
            sm.save_checkpoint(ev.session_id, count)

        state = json.loads((Path(td) / "state" / "counter-session_state.json").read_text())
        assert state["exchange_count"] == 3


# ────────────────────────────────────────────────────────────────────
# 5. WhatsApp regex used to capture "00 PM] Alice" as the author for
#    the international [date, time AM/PM] format. It must now extract
#    just "Alice".
# ────────────────────────────────────────────────────────────────────
def test_whatsapp_international_format():
    from memorius.normalizers import normalize_whatsapp

    sample = (
        "[1/15/24, 12:00:00 PM] Alice: Hello!\n"
        "[1/15/24, 12:00:01 PM] Bob: Hi!\n"
    )
    out = normalize_whatsapp(sample, "test")
    assert "**Alice**" in out, "should extract Alice as author"
    assert "**Bob**" in out, "should extract Bob as author"
    # The broken pattern produced "00 PM] Alice" — make sure that's gone.
    assert "00 PM] Alice" not in out
    assert "PM] Alice" not in out


def test_whatsapp_us_format():
    from memorius.normalizers import normalize_whatsapp

    sample = "1/15/24, 12:00 PM - Carol: Welcome!\n"
    out = normalize_whatsapp(sample, "test")
    assert "**Carol**" in out


def test_whatsapp_system_message_recognized():
    """A bare joined/invite message should be tagged as a system event."""
    from memorius.normalizers import normalize_whatsapp

    sample = (
        "[1/15/24, 12:00:00 PM] Alice: Hello!\n"
        "Alice joined using this group's invite link\n"
    )
    out = normalize_whatsapp(sample, "test")
    assert "**Alice**" in out
    # The system notice should be present, but in italics, not as a fake author.
    assert "joined" in out


# ────────────────────────────────────────────────────────────────────
# 6. LICENSE must exist at the repo root and be shipped in the
#    package data, so that license-scanners (scancode, licensee,
#    cargo-about) don't flag this as missing.
# ────────────────────────────────────────────────────────────────────
def test_license_file_exists():
    repo_root = Path(__file__).resolve().parent.parent
    assert (repo_root / "LICENSE").is_file(), (
        "LICENSE file must exist at the repo root for standard "
        "MIT-license tooling to find it."
    )
    text = (repo_root / "LICENSE").read_text()
    assert "MIT License" in text or "MIT" in text


def test_package_data_includes_license():
    """The wheel must include LICENSE, manifest.yaml, and the hook wrapper."""
    from importlib.resources import files
    pkg_data = files("memorius.data")
    assert pkg_data is not None
    # importlib.resources returns a MultiplexedPath or Traversable
    items = [p.name for p in pkg_data.iterdir()]
    assert "LICENSE" in items
    assert "manifest.yaml" in items
    assert "memorius-hook.sh" in items
    # And examples/ subdir:
    examples = [p.name for p in pkg_data.joinpath("examples").iterdir()]
    assert "quickstart.py" in examples


# ────────────────────────────────────────────────────────────────────
# 7. Hardcoded "0.1.0" fallbacks should be replaced with the real
#    __version__. The plugin-gen and hook CLIs had stale "0.1.0" strings
#    that would lie if __version__ were bumped.
# ────────────────────────────────────────────────────────────────────
def test_plugin_gen_version_does_not_hardcode_0_1_0():
    import memorius.plugin_gen.cli as pg
    # When manifest doesn't specify a version, we fall back to the
    # running __version__ — not a literal string.
    from memorius import __version__
    manifest = {"name": "x"}  # no version key
    # We can't easily call generate_*, so just assert the constant
    # is the real version.
    assert pg._MEMORIUS_VERSION == __version__


def test_cli_version_flags_print_running_version():
    """memorius --version, memorius-hook --version, memorius-plugin-gen --version
    should all print the actual __version__, not a stale literal."""
    from memorius import __version__

    for script in ("memorius", "memorius-hook", "memorius-plugin-gen"):
        script_path = shutil.which(script)
        if not script_path:
            pytest.skip(f"{script} not found in PATH")
        proc = subprocess.run(
            [script_path, "--version"],
            capture_output=True, text=True, timeout=30,
        )
        combined = proc.stdout + proc.stderr
        assert __version__ in combined, (
            f"{script} --version output {combined!r} does not contain "
            f"the running version {__version__!r}"
        )
