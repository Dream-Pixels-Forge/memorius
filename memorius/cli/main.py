"""memorius CLI — interact with your memory palace from the terminal.

Usage:
  memorius init              Initialize a new palace
  memorius status            Show palace status
  memorius store <text>      Store a memory
  memorius search <query>    Semantic search across memories
  memorius mine <file>       Mine memories from a transcript file
  memorius diary <session>   Write a diary entry (interactive)
  memorius diaries           List recent diary entries
  memorius ls [palace]       Explore palace hierarchy
  memorius serve             Start the MCP server (stdio)
  memorius serve-rest        Start the REST API server
  memorius config            Show current config
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from memorius import __version__
from memorius.config import load_config, DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_PATH
from memorius.palace import PalaceEngine

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("memorius.cli")


def main():
    parser = argparse.ArgumentParser(
        "memorius",
        description="Memory palace for any AI agent — store, search, and organize memories.",
    )
    parser.add_argument("--version", action="store_true", help="Show version")
    parser.add_argument("--config", default=None, help="Path to config file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Initialize a new palace")
    subparsers.add_parser("status", help="Show palace status")

    store_p = subparsers.add_parser("store", help="Store a memory")
    store_p.add_argument("content", nargs="?", default=None, help="Memory content")
    store_p.add_argument("--palace", default="main", help="Palace name")
    store_p.add_argument("--wing", default="default", help="Wing name")
    store_p.add_argument("--room", default="default", help="Room name")
    store_p.add_argument("--drawer", default="default", help="Drawer name")

    search_p = subparsers.add_parser("search", help="Semantic search")
    search_p.add_argument("query", nargs="?", default=None, help="Search query")
    search_p.add_argument("--n", type=int, default=10, help="Number of results")
    search_p.add_argument("--palace", default=None, help="Filter by palace")
    search_p.add_argument("--wing", default=None, help="Filter by wing")

    mine_p = subparsers.add_parser("mine", help="Mine memories from a transcript")
    mine_p.add_argument("file", nargs="?", default=None, help="Transcript file path")
    mine_p.add_argument("--palace", default="main", help="Palace name")
    mine_p.add_argument("--text", default=None, help="Transcript text (inline)")

    diary_p = subparsers.add_parser("diary", help="Write a diary entry")
    diary_p.add_argument("session_id", nargs="?", default=None, help="Session ID")
    diary_p.add_argument("--title", default="", help="Diary title")
    diary_p.add_argument("--summary", default="", help="Diary summary")
    diary_p.add_argument("--content", default="", help="Diary content")
    diary_p.add_argument("--palace", default="main", help="Palace name")

    subparsers.add_parser("diaries", help="List recent diary entries")
    subparsers.add_parser("ls", help="Explore palace hierarchy")

    serve_p = subparsers.add_parser("serve", help="Start MCP server (stdio)")
    serve_p.add_argument("--port", type=int, default=8911, help="Not used for stdio")

    serve_rest_p = subparsers.add_parser("serve-rest", help="Start REST API server")
    serve_rest_p.add_argument("--port", type=int, default=8912, help="Port")
    serve_rest_p.add_argument("--host", default="127.0.0.1", help="Host")

    config_p = subparsers.add_parser("config", help="Show configuration")
    config_p.add_argument("--show", action="store_true", default=True, help="Show config")
    config_p.add_argument("--path", action="store_true", help="Show config file path")

    args = parser.parse_args()

    if args.version:
        print(f"memorius v{__version__}")
        return

    if args.debug:
        logging.getLogger("memorius").setLevel(logging.DEBUG)

    if args.command is None:
        parser.print_help()
        return

    # Load config and create engine
    config = load_config(args.config)
    engine = PalaceEngine(config)

    # Dispatch
    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "store": cmd_store,
        "search": cmd_search,
        "mine": cmd_mine,
        "diary": cmd_diary,
        "diaries": cmd_diaries,
        "ls": cmd_ls,
        "serve": cmd_serve,
        "serve-rest": cmd_serve_rest,
        "config": cmd_config,
    }
    handler = commands.get(args.command)
    if handler:
        handler(engine, args, config)
    else:
        print(f"Unknown command: {args.command}")


def cmd_init(engine, args, config):
    """Initialize the palace — ensures config dir and storage exists."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_CONFIG_PATH.exists():
        from memorius.config import DEFAULT_CONFIG_YAML
        DEFAULT_CONFIG_PATH.write_text(DEFAULT_CONFIG_YAML)
        print(f"Created config: {DEFAULT_CONFIG_PATH}")
    else:
        print(f"Config exists: {DEFAULT_CONFIG_PATH}")

    # Ensure default palace exists
    engine._meta.ensure_palace("main", "Main palace")
    print("Palace initialized: main")
    print(f"Storage: {config.get('storage', {}).get('path', '~/.memorius/data')}")
    print(f"Embeddings: {config.get('embeddings', {}).get('provider', 'sentence-transformers')}")


def cmd_status(engine, args, config):
    """Show palace status."""
    status = engine.status()
    print(f"  Palaces:      {status['palaces']}")
    print(f"  Memories:     {status['memories']}")
    print(f"  Recent diaries: {status['diaries']}")
    print(f"  Embeddings:   {status['embedding_provider']} (dim={status['embedding_dimension']})")
    print()
    if status.get("recent_diaries"):
        print("Recent diaries:")
        for d in status["recent_diaries"]:
            print(f"  [{d['created_at'][:19]}] {d.get('title', 'untitled')} ({d['session_id']})")
    else:
        print("No diaries yet.")


def cmd_store(engine, args, config):
    """Store a memory. Reads from stdin if no content arg."""
    content = args.content
    if not content:
        content = sys.stdin.read().strip()
    if not content:
        print("Error: content required (pass as argument or pipe to stdin)")
        return

    memory = engine.store(
        content=content,
        palace=args.palace,
        wing=args.wing,
        room=args.room,
        drawer=args.drawer,
    )
    print(f"Stored: {memory.id}")
    print(f"  Path: {memory.palace}/{memory.wing}/{memory.room}/{memory.drawer}")


def cmd_search(engine, args, config):
    """Semantic search across memories."""
    query = args.query
    if not query:
        query = sys.stdin.read().strip()
    if not query:
        print("Error: query required (pass as argument or pipe to stdin)")
        return

    results = engine.search(
        query=query,
        palace=args.palace,
        wing=args.wing,
        n_results=args.n,
    )
    print(f"Search: \"{query}\"")
    print(f"Results: {len(results)}")
    print()
    for i, m in enumerate(results, 1):
        print(f"{i}. [{m.palace}/{m.wing}/{m.room}/{m.drawer}]")
        print(f"   {m.content[:200]}")
        if len(m.content) > 200:
            print("   ...")
        print()


def cmd_mine(engine, args, config):
    """Mine memories from a transcript."""
    text = args.text
    if not text and args.file:
        text = Path(args.file).read_text()
    if not text:
        text = sys.stdin.read().strip()
    if not text:
        print("Error: transcript required (--text, <file>, or stdin)")
        return

    memories = engine.mine(
        transcript=text,
        palace=args.palace,
    )
    print(f"Mined {len(memories)} memories into {args.palace}/conversations/default/default/mined")


def cmd_diary(engine, args, config):
    """Write a diary entry."""
    session_id = args.session_id or input("Session ID: ").strip()
    if not session_id:
        print("Error: session_id required")
        return
    title = args.title or input("Title: ").strip()
    summary = args.summary or input("Summary: ").strip()

    entry = engine.write_diary(
        session_id=session_id,
        palace=args.palace,
        title=title,
        summary=summary,
        content=args.content,
    )
    print(f"Diary written: {entry['id']}")


def cmd_diaries(engine, args, config):
    """List recent diary entries."""
    diaries = engine._meta.list_diaries(limit=10)
    if not diaries:
        print("No diary entries.")
        return
    for d in diaries:
        print(f"[{d['created_at'][:19]}] {d['title'] or 'untitled'}")
        print(f"  Session: {d['session_id']} | Palace: {d['palace']}")
        if d['summary']:
            print(f"  Summary: {d['summary'][:200]}")
        print()


def cmd_ls(engine, args, config):
    """Explore palace hierarchy."""
    # Default: list palaces
    from memorius.config import load_config
    palaces = engine._meta.list_palaces()
    if not palaces:
        print("No palaces. Run: memorius init")
        return
    for p in palaces:
        print(f"{p['name']}/")
        wings = engine._meta.list_wings(p['name'])
        for w in wings:
            print(f"  {w['name']}/")
            rooms = engine._meta.list_rooms(p['name'], w['name'])
            for r in rooms[:5]:
                print(f"    {r['name']}/")
                drawers = engine._meta.list_drawers(p['name'], w['name'], r['name'])
                for dr in drawers:
                    print(f"      {dr['name']} ({dr['memory_count']} memories)")
            if len(rooms) > 5:
                print(f"    ... and {len(rooms) - 5} more rooms")


def cmd_serve(engine, args, config):
    """Start the MCP server (stdio)."""
    from memorius.mcp_server import McpServer
    server = McpServer(engine)
    print("memorius MCP server starting (stdio)...", file=sys.stderr)
    server.run()


def cmd_serve_rest(engine, args, config):
    """Start the REST API server."""
    from memorius.rest_server import run_rest_server
    config_server = config.get("server", {})
    host = args.host or config_server.get("host", "127.0.0.1")
    port = args.port or config_server.get("rest_port", 8912)
    run_rest_server(engine, host=host, port=port)


def cmd_config(engine, args, config):
    """Show current configuration."""
    if args.path:
        path = DEFAULT_CONFIG_PATH
        print(path)
        print(f"  Exists: {path.exists()}")
        return
    print(json.dumps(config, indent=2, default=str))


if __name__ == "__main__":
    main()
