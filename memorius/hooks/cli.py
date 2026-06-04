#!/usr/bin/env python3
"""
Universal Hook CLI — entry point for `memorius-hook`.

Reads JSON from stdin (from any supported AI agent), processes through
the lifecycle engine, and outputs the appropriate response.

Usage:
  cat payload.json | memorius-hook run
  cat payload.json | memorius-hook run --agent claude-code
  memorius-hook run --event precompact < payload.json
  memorius-hook init-config   # generate default ~/.memorius/hooks.yaml
  memorius-hook status        # show hook state
"""

import json
import logging
import sys
from pathlib import Path

from . import (
    HookEvent,
    HookEventType,
    HookResult,
    detect_agent,
)
from .engine import HookConfig, HookEngine

logger = logging.getLogger("memorius.hooks.cli")

# Silence httpx/uvicorn logs unless we're debugging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)


def _init_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def cmd_run(args):
    """Run the hook lifecycle: read stdin, detect agent, process event, output result."""
    import argparse

    # Accept either a Namespace (from main) or raw args (for testing)
    if isinstance(args, argparse.Namespace):
        parsed = args
        parsed.verbose = False
        parsed.mock_input = None
    else:
        parser = argparse.ArgumentParser("memorius-hook run")
        parser.add_argument("--agent", choices=["auto", "claude-code", "codex", "gemini-cli", "openclaw"], default="auto",
                            help="AI agent to emulate (auto-detect from stdin if omitted)")
        parser.add_argument("--config", default="~/.memorius/hooks.yaml",
                            help="Path to hooks lifecycle YAML config")
        parser.add_argument("--event", default=None,
                            help="Force a specific event type (session_start, session_stop, pre_compress)")
        parser.add_argument("--verbose", "-v", action="store_true",
                            help="Enable debug logging")
        parser.add_argument("--mock-input", default=None,
                            help="Path to mock JSON input file (for testing without real agent)")
        parsed = parser.parse_args(args)

    _init_logging(parsed.verbose)

    # Read input
    if parsed.mock_input:
        with open(parsed.mock_input) as f:
            raw_input = f.read()
    else:
        raw_input = sys.stdin.read()

    if not raw_input or raw_input.strip() == "":
        logger.warning("No input received on stdin")
        # Return empty JSON as required by hook protocols
        print("{}")
        return 0

    # Parse JSON
    try:
        data = json.loads(raw_input)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON input: {e}")
        print("{}")
        return 1

    # Log raw input for debugging
    logger.debug(f"Raw input keys: {list(data.keys()) if isinstance(data, dict) else 'list'}")

    # Detect agent
    if parsed.agent and parsed.agent != "auto":
        adapter_map = {
            "claude-code": __import__("memorius.hooks", fromlist=["ClaudeCodeAdapter"]),
            "codex": __import__("memorius.hooks", fromlist=["CodexAdapter"]),
            "gemini-cli": __import__("memorius.hooks", fromlist=["GeminiCliAdapter"]),
        }
        # Use auto-detect even with explicit agent to reuse parsing
        adapter_cls = detect_agent(data)
        logger.info(f"Using explicit agent '{parsed.agent}', auto-detected adapter: {adapter_cls.agent_name}")
    else:
        adapter_cls = detect_agent(data)
        logger.info(f"Auto-detected agent: {adapter_cls.agent_name}")

    # Parse into universal event
    event = adapter_cls.parse(data)

    # Override event type if specified
    if parsed.event:
        try:
            event.event_type = HookEventType(parsed.event)
        except ValueError:
            logger.warning(f"Unknown event type '{parsed.event}', using detected {event.event_type.value}")

    # Load configuration
    config_path = Path(parsed.config).expanduser()
    config = HookConfig.from_yaml(config_path)

    # Process through engine
    engine = HookEngine(config)
    result = engine.process(event)

    # Output result as JSON
    output = {
        "decision": result.action,
    }
    if result.reason:
        output["reason"] = result.reason

    print(json.dumps(output))
    return 0


def cmd_init_config(args: list[str]):
    """Generate the default hooks.yaml configuration."""
    from .engine import DEFAULT_CONFIG_YAML

    config_path = Path("~/.memorius/hooks.yaml").expanduser()

    if config_path.exists():
        print(f"Config already exists: {config_path}")
        return 1

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(DEFAULT_CONFIG_YAML)
    print(f"Generated default config: {config_path}")
    return 0


def cmd_status(args: list[str]):
    """Show hook state summary."""
    state_dir = Path("~/.memorius/hook_state").expanduser()
    if not state_dir.exists():
        print("No hook state found (no hooks have run yet).")
        return 0

    state_files = list(state_dir.glob("*_state.json"))
    if not state_files:
        print("No session state tracked.")
        return 0

    print(f"Hook State Directory: {state_dir}")
    print(f"Tracked Sessions: {len(state_files)}")
    print()
    for sf in sorted(state_files, key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
        try:
            data = json.loads(sf.read_text())
            last_save = data.get("last_save", 0)
            from datetime import datetime
            ts = datetime.fromtimestamp(last_save).strftime("%Y-%m-%d %H:%M:%S") if last_save else "never"
            session_id = data.get("session_id", sf.stem.replace("_state", ""))
            print(f"  {session_id[:60]:60s}  last save: {ts}")
        except (json.JSONDecodeError, OSError):
            print(f"  {sf.name}  (corrupt)")

    return 0


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        "memorius-hook",
        description="Universal Memorius hook lifecycle adapter — works with any AI agent.",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")

    subparsers = parser.add_subparsers(dest="command", help="Subcommand")

    run_parser = subparsers.add_parser("run", help="Run the hook lifecycle (reads stdin)")
    run_parser.add_argument("--event", required=True, help="Hook event name (stop, precompact, session-start, etc.)")
    run_parser.add_argument("--agent", default="auto", help="Agent harness (auto-detect if omitted)")
    run_parser.add_argument("--config", default="~/.memorius/hooks.yaml", help="Path to hooks.yaml config")

    subparsers.add_parser("init-config", help="Generate default hooks.yaml")
    subparsers.add_parser("status", help="Show hook state")

    args = parser.parse_args()

    if args.version:
        try:
            from .. import __version__
            v = __version__
        except ImportError:
            v = "0.1.0"
        print(f"memorius-hook v{v}")
        return 0

    if args.command == "run":
        sys.exit(cmd_run(args))
    elif args.command == "init-config":
        sys.exit(cmd_init_config(sys.argv[2:]))
    elif args.command == "status":
        sys.exit(cmd_status(sys.argv[2:]))
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    main()
