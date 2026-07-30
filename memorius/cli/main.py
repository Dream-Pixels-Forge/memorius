"""memorius CLI — interact with your memory vault from the terminal.

Usage:
  memorius init              Initialize a new vault
  memorius setup             Download ONNX model and initialize vault
  memorius status            Show vault status
  memorius store <text>      Store a memory
  memorius search <query>    Semantic search across memories
  memorius mine <file>       Mine memories from a transcript file
  memorius diary <session>   Write a diary entry (interactive)
  memorius diaries           List recent diary entries
  memorius ls [vault]        Explore vault hierarchy
  memorius get <id>          Get a memory by ID
  memorius update <id>       Update a memory's content or metadata
  memorius delete <id>       Delete a memory by ID (validation + confirmation)
  memorius prune             Find and archive stale memories by decay score
  memorius serve             Start the MCP server (stdio)
  memorius serve-rest        Start the REST API server
  memorius config            Show current config
  memorius obsidian list     List notes in an Obsidian vault
  memorius obsidian import   Import Obsidian notes as memories
  memorius obsidian export   Export memories as Obsidian notes
  memorius web <query>     Search the internet (web fallback)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from memorius import __version__
from memorius.config import load_config, DEFAULT_CONFIG_DIR, DEFAULT_CONFIG_PATH
from memorius.vault import VaultEngine
from memorius.web_search import web_fallback_enabled, should_fallback

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("memorius.cli")


def _ensure_utf8_streams():
    """Force UTF-8 on stdout/stderr so emoji/icons (e.g. the factcheck verdict
    glyphs) don't crash on Windows cp1252 consoles. Best-effort: a stream
    that can't be reconfigured (e.g. piped to a file) is left untouched."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main():
    _ensure_utf8_streams()
    parser = argparse.ArgumentParser(
        "memorius",
        description="Memory vault for any AI agent — store, search, and organize memories.",
    )
    parser.add_argument("--version", action="store_true", help="Show version")
    parser.add_argument("--config", default=None, help="Path to config file")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Initialize a new vault")
    
    setup_p = subparsers.add_parser("setup", help="Download ONNX model and initialize vault")
    setup_p.add_argument("--force", action="store_true", help="Re-download model even if exists")
    setup_p.add_argument("--skip-model", action="store_true", help="Skip model download, only init vault")
    
    subparsers.add_parser("status", help="Show vault status")

    store_p = subparsers.add_parser("store", help="Store a memory")
    store_p.add_argument("content", nargs="?", default=None, help="Memory content")
    store_p.add_argument("--vault", default="main", help="Vault name")
    store_p.add_argument("--shelf", default="default", help="Shelf name")
    store_p.add_argument("--folder", default="default", help="Folder name")
    store_p.add_argument("--note", default="default", help="Note name")
    store_p.add_argument("--ttl", type=int, default=None, metavar="DAYS",
                         help="Time-to-live in days; memory expires after N days")

    search_p = subparsers.add_parser("search", help="Semantic search")
    search_p.add_argument("query", nargs="?", default=None, help="Search query")
    search_p.add_argument("--n", type=int, default=10, help="Number of results")
    search_p.add_argument("--vault", default=None, help="Filter by vault")
    search_p.add_argument("--shelf", default=None, help="Filter by shelf")
    search_p.add_argument("--folder", default=None, help="Filter by folder (Chroma metadata)")
    search_p.add_argument("--note", default=None, help="Filter by note (Chroma metadata)")
    search_p.add_argument("--tag", action="append", default=None, help="Filter by tag (repeatable; memory must carry ALL supplied tags)")
    search_p.add_argument("--expand-graph", action="store_true", help="Also pull in 1-hop graph-linked memories (\"you also worked on X\")")
    search_p.add_argument("--rerank", action="store_true", help="Cross-encoder rerank results (requires memorius[ranker])")
    search_p.add_argument("--web", action="store_true", help="Fall back to web search if local recall is thin")

    mine_p = subparsers.add_parser("mine", help="Mine memories from a transcript")
    mine_p.add_argument("file", nargs="?", default=None, help="Transcript file path")
    mine_p.add_argument("--vault", default="main", help="Vault name")
    mine_p.add_argument("--text", default=None, help="Transcript text (inline)")

    diary_p = subparsers.add_parser("diary", help="Write a diary entry")
    diary_p.add_argument("session_id", nargs="?", default=None, help="Session ID")
    diary_p.add_argument("--title", default="", help="Diary title")
    diary_p.add_argument("--summary", default="", help="Diary summary")
    diary_p.add_argument("--content", default="", help="Diary content")
    diary_p.add_argument("--vault", default="main", help="Vault name")
    diary_p.add_argument("--exchange-count", type=int, default=0, help="Number of exchanges in session")

    subparsers.add_parser("diaries", help="List recent diary entries")
    p = subparsers.add_parser("ls", help="Explore vault hierarchy")
    p.add_argument("--vault", default=None, help="Vault to explore (default: all)")

    serve_p = subparsers.add_parser("serve", help="Start MCP server (stdio)")
    serve_p.add_argument("--port", type=int, default=8911, help="Not used for stdio")

    serve_rest_p = subparsers.add_parser("serve-rest", help="Start REST API server")
    serve_rest_p.add_argument("--port", type=int, default=None, help="Port")
    serve_rest_p.add_argument("--host", default=None, help="Host (default: 127.0.0.1)")
    serve_rest_p.add_argument("--daemon", action="store_true", help="Run as background daemon")
    serve_rest_p.add_argument("--stop", action="store_true", help="Stop running daemon")
    serve_rest_p.add_argument("--pid-file", default=None, help="PID file path")
    serve_rest_p.add_argument("--tls-cert", default=None, help="Path to TLS certificate file (PEM)")
    serve_rest_p.add_argument("--tls-key", default=None, help="Path to TLS private key file (PEM)")

    config_p = subparsers.add_parser("config", help="Show configuration")
    config_p.add_argument("--show", action="store_true", default=True, help="Show config")
    config_p.add_argument("--path", action="store_true", help="Show config file path")

    # ── New v0.2.0 commands ──
    consolidate_p = subparsers.add_parser("consolidate", help="Consolidate similar memories")
    consolidate_p.add_argument("--vault", default=None, help="Filter by vault")
    consolidate_p.add_argument("--threshold", type=float, default=0.80, help="Similarity threshold (0-1)")
    consolidate_p.add_argument("--dry-run", action="store_true", help="Preview without changes")

    extract_p = subparsers.add_parser("extract", help="Extract memories from conversation")
    extract_p.add_argument("file", nargs="?", default=None, help="Conversation file path")
    extract_p.add_argument("--text", default=None, help="Conversation text (inline)")
    extract_p.add_argument("--vault", default="main", help="Target vault")
    extract_p.add_argument("--shelf", default="extracted", help="Target shelf")
    extract_p.add_argument("--backend", default="auto", choices=["auto", "openai", "ollama", "regex"], help="LLM backend")

    factcheck_p = subparsers.add_parser("factcheck", help="Fact-check against stored memories")
    factcheck_p.add_argument("statement", nargs="?", default=None, help="Statement to verify")
    factcheck_p.add_argument("--vault", default=None, help="Filter by vault")
    factcheck_p.add_argument("--web", action="store_true", help="Cross-check uncertain claims against the web")

    context_p = subparsers.add_parser("context", help="Get memory context for injection")
    context_p.add_argument("query", nargs="?", default=None, help="Topic to search for")
    context_p.add_argument("--vault", default=None, help="Filter by vault")
    context_p.add_argument("--max", type=int, default=5, help="Max items")
    context_p.add_argument("--web", action="store_true", help="Augment with web results if no local context")

    web_p = subparsers.add_parser("web", help="Search the internet (web fallback)")
    web_p.add_argument("query", nargs="?", default=None, help="Search query")
    web_p.add_argument("--max", type=int, default=5, help="Max results")
    web_p.add_argument("--provider", default=None, help="Provider override (duckduckgo|mock)")

    profile_p = subparsers.add_parser("profile", help="Build session memory profile")
    profile_p.add_argument("session_id", nargs="?", default=None, help="Session ID")
    profile_p.add_argument("--vault", default="main", help="Vault name")

    subparsers.add_parser("stats", help="Show memory statistics")

    delete_p = subparsers.add_parser("delete", help="Delete a memory by ID")
    delete_p.add_argument("memory_id", help="Memory UUID to delete")
    delete_p.add_argument("--vault", default=None, help="Vault scope (must match memory's vault)")
    delete_p.add_argument("--shelf", default=None, help="Shelf scope (must match memory's shelf)")
    delete_p.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    delete_p.add_argument("--dry-run", action="store_true", help="Preview without deleting")

    get_p = subparsers.add_parser("get", help="Get a memory by ID")
    get_p.add_argument("memory_id", help="Memory UUID to retrieve")
    get_p.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")

    update_p = subparsers.add_parser("update", help="Update a memory's content or metadata")
    update_p.add_argument("memory_id", help="Memory UUID to update")
    update_p.add_argument("--content", default=None, help="New content (omit to keep existing)")
    update_p.add_argument("--metadata", default=None, help="JSON metadata to shallow-merge")
    update_p.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")

    prune_p = subparsers.add_parser("prune", help="Find and archive stale memories")
    prune_p.add_argument("--threshold", type=float, default=0.1, help="Decay score threshold (default: 0.1)")
    prune_p.add_argument("--dry-run", action="store_true", help="Preview without touching memories")
    prune_p.add_argument("--delete", dest="hard_delete", action="store_true", help="Hard-delete instead of soft-archive")
    prune_p.add_argument("--json", dest="output_json", action="store_true", help="Output as JSON")

    export_p = subparsers.add_parser("export", help="Export vault to JSON or Markdown")
    export_p.add_argument("dest", help="Output file path (.json) or directory (for markdown)")
    export_p.add_argument("--format", choices=["json", "markdown"], default="json", help="Export format (default: json)")

    import_p = subparsers.add_parser("import", help="Import vault from a JSON export")
    import_p.add_argument("src", help="JSON export file to import")
    import_p.add_argument("--replace", action="store_true", help="Overwrite existing memories instead of skipping")

    subparsers.add_parser("doctor", help="Run health checks on the vault")

    list_p = subparsers.add_parser("list", help="List memories with cursor pagination")
    list_p.add_argument("--vault", help="Filter by vault")
    list_p.add_argument("--limit", type=int, default=10, help="Max results per page (default: 10)")
    list_p.add_argument("--cursor", help="Cursor for next page (timestamp)")

    # ── Obsidian subcommands ──
    obsidian_p = subparsers.add_parser("obsidian", help="Interact with Obsidian vaults")
    obsidian_sub = obsidian_p.add_subparsers(dest="subcommand")

    list_p = obsidian_sub.add_parser("list", help="List notes in Obsidian vault")
    list_p.add_argument("--vault", dest="obsidian_vault", default=None, help="Path to Obsidian vault (default: $OBSIDIAN_VAULT_PATH or ~/Documents/Obsidian Vault)")

    import_p = obsidian_sub.add_parser("import", help="Import Obsidian notes as memories")
    import_p.add_argument("--vault", dest="obsidian_vault", default=None, help="Path to Obsidian vault")
    import_p.add_argument("--target-vault", default="main", help="Target memorius vault (default: main)")
    import_p.add_argument("--target-shelf", default="obsidian", help="Target memorius shelf (default: obsidian)")
    import_p.add_argument("--tag", default=None, help="Only import notes with this tag")
    import_p.add_argument("--dry-run", action="store_true", help="Show what would be imported without writing")

    export_p = obsidian_sub.add_parser("export", help="Export memorius memories as Obsidian notes")
    export_p.add_argument("--vault", dest="obsidian_vault", default=None, help="Path to Obsidian vault")
    export_p.add_argument("--source-vault", default="main", help="Source memorius vault (default: main)")
    export_p.add_argument("--source-shelf", default=None, help="Filter by shelf (default: all)")
    export_p.add_argument("--dry-run", action="store_true", help="Show what would be exported without writing")

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
    engine = VaultEngine(config)

    # Dispatch
    commands = {
        "init": cmd_init,
        "setup": cmd_setup,
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
        "obsidian": cmd_obsidian,
        "consolidate": cmd_consolidate,
        "extract": cmd_extract,
        "factcheck": cmd_factcheck,
        "context": cmd_context,
        "web": cmd_web,
        "profile": cmd_profile,
        "stats": cmd_stats,
        "delete": cmd_delete,
        "get": cmd_get,
        "update": cmd_update,
        "prune": cmd_prune,
        "export": cmd_export,
        "import": cmd_import,
        "doctor": cmd_doctor,
        "list": cmd_list,
    }
    handler = commands.get(args.command)
    if handler:
        handler(engine, args, config)
    else:
        print(f"Unknown command: {args.command}")


def cmd_init(engine, args, config):
    """Initialize the vault — ensures config dir and storage exists."""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_CONFIG_PATH.exists():
        from memorius.config import DEFAULT_CONFIG_YAML
        DEFAULT_CONFIG_PATH.write_text(DEFAULT_CONFIG_YAML)
        print(f"Created config: {DEFAULT_CONFIG_PATH}")
    else:
        print(f"Config exists: {DEFAULT_CONFIG_PATH}")

    engine._meta.ensure_vault("main", "Main vault")
    print("Vault initialized: main")
    print(f"Storage: {config.get('storage', {}).get('path', '~/.memorius/data')}")
    print(f"Embeddings: {config.get('embeddings', {}).get('provider', 'chroma-default')}")


def cmd_setup(engine, args, config):
    """Download ONNX model and initialize vault."""
    from memorius.model_download import is_model_downloaded, setup_model, get_model_path
    
    print("memorius setup")
    print("=" * 50)
    
    # Step 1: Initialize vault
    print("\n1. Initializing vault...")
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if not DEFAULT_CONFIG_PATH.exists():
        from memorius.config import DEFAULT_CONFIG_YAML
        DEFAULT_CONFIG_PATH.write_text(DEFAULT_CONFIG_YAML)
        print(f"   Created config: {DEFAULT_CONFIG_PATH}")
    else:
        print(f"   Config exists: {DEFAULT_CONFIG_PATH}")
    
    engine._meta.ensure_vault("main", "Main vault")
    print("   Vault initialized: main")
    
    # Step 2: Download ONNX model
    if args.skip_model:
        print("\n2. Skipping model download (--skip-model)")
    else:
        print("\n2. Setting up ONNX model...")
        if is_model_downloaded() and not args.force:
            print(f"   Model already downloaded: {get_model_path()}")
        else:
            if args.force:
                print("   Force mode: re-downloading model...")
            success = setup_model(force=args.force)
            if not success:
                print("\nSetup completed with errors.")
                print("The vault is ready, but the ONNX model failed to download.")
                print("You can try again later with: memorius setup --force")
                return
    
    # Step 3: Verify
    print("\n3. Verification...")
    status = engine.status()
    print(f"   Embeddings: {status['embedding_provider']} (dim={status['embedding_dimension']})")
    
    print("\n" + "=" * 50)
    print("Setup complete!")
    print("\nNext steps:")
    print("  memorius store 'My first memory'  # Store a memory")
    print("  memorius search 'first memory'    # Search for it")
    print("  memorius status                   # Check vault status")


def cmd_status(engine, args, config):
    """Show vault status."""
    status = engine.status()
    print(f"  Vaults:       {status['vaults']}")
    print(f"  Memories:     {status['memories']}")
    print(f"  Embeddings:   {status['embedding_provider']} (dim={status['embedding_dimension']})")
    print()
    diaries = engine._meta.list_diaries(limit=5)
    if diaries:
        print("Recent diaries:")
        for d in diaries:
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
        vault=args.vault,
        shelf=args.shelf,
        folder=args.folder,
        note=args.note,
        ttl_days=args.ttl,
    )
    print(f"Stored: {memory.id}")
    print(f"  Path: {memory.vault}/{memory.shelf}/{memory.folder}/{memory.note}")
    if args.ttl is not None:
        print(f"  Expires: {args.ttl} days")


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
        vault=args.vault,
        shelf=args.shelf,
        limit=args.n,
        expand_graph=getattr(args, "expand_graph", False),
        folder=getattr(args, "folder", None),
        note=getattr(args, "note", None),
        tags=getattr(args, "tag", None),
        rerank=getattr(args, "rerank", False),
    )
    print(f'Search: "{query}"')
    if getattr(args, "expand_graph", False):
        print("(graph expansion: on)")
    print(f"Results: {len(results)}")
    print()
    for i, m in enumerate(results, 1):
        print(f"{i}. [{m.vault}/{m.shelf}/{m.folder}/{m.note}]")
        print(f"   {m.content[:200]}")
        if len(m.content) > 200:
            print("   ...")
        print()

    # Web fallback — only if local recall is thin ("if needed").
    if web_fallback_enabled(args, config) and should_fallback(len(results), config):
        from memorius.web_search import get_web_provider
        provider = get_web_provider(config)
        if provider:
            web = provider.search(
                query,
                max_results=config.get("retrieval", {}).get("web_max_results", 5),
            )
            print("Web results (from internet):")
            if not web:
                print("  (no web results)")
            for r in web:
                print(f"  - {r.title}")
                print(f"    {r.url}")
                if r.snippet:
                    print(f"    {r.snippet[:160]}")


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
        text=text,
        vault=args.vault,
    )
    print(f"Mined {len(memories)} memories into {args.vault}/conversations/mined/transcript")


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
        vault=args.vault,
        title=title,
        summary=summary,
        content=args.content,
        exchange_count=args.exchange_count,
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
        print(f"  Session: {d['session_id']} | Vault: {d['vault']}")
        if d['summary']:
            print(f"  Summary: {d['summary'][:200]}")
        print()


def cmd_ls(engine, args, config):
    """Explore vault hierarchy."""
    vaults = engine._meta.list_vaults()
    if not vaults:
        print("No vaults. Run: memorius init")
        return
    for v in vaults:
        print(f"{v['name']}/")
        shelves = engine._meta.list_shelves(v['name'])
        for sh in shelves:
            print(f"  {sh['name']}/")
            folders = engine._meta.list_folders(v['name'], sh['name'])
            for f in folders[:5]:
                print(f"    {f['name']}/")
                notes = engine._meta.list_notes(v['name'], sh['name'], f['name'])
                for n in notes:
                    print(f"      {n['name']} ({n['memory_count']} memories)")
            if len(folders) > 5:
                print(f"    ... and {len(folders) - 5} more folders")


def cmd_serve(engine, args, config):
    """Start the MCP server (stdio)."""
    from memorius.mcp_server import McpServer
    server = McpServer(engine)
    print("memorius MCP server starting (stdio)...", file=sys.stderr)
    server.run()


def cmd_serve_rest(engine, args, config):
    """Start the REST API server."""
    config_server = config.get("server", {})
    host = args.host or config_server.get("host", "127.0.0.1")
    port = args.port or config_server.get("rest_port", 8912)
    pid_file = Path(args.pid_file or (DEFAULT_CONFIG_DIR / "serve.pid"))

    if getattr(args, "stop", False):
        _stop_daemon(pid_file)
        return

    if getattr(args, "daemon", False):
        _start_daemon(
            engine, host, port, pid_file,
            tls_cert=getattr(args, "tls_cert", None),
            tls_key=getattr(args, "tls_key", None),
        )
    else:
        from memorius.rest_server import run_rest_server
        run_rest_server(
            engine, host=host, port=port,
            tls_cert=getattr(args, "tls_cert", None),
            tls_key=getattr(args, "tls_key", None),
        )


def _stop_daemon(pid_file: Path):
    """Stop a running daemon by PID file."""
    import os
    import signal
    import time

    if not pid_file.exists():
        print("No daemon running (no PID file)")
        return

    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        pid_file.unlink(missing_ok=True)
        print("Invalid PID file, removed")
        return

    # Check if process is alive
    alive = True
    try:
        os.kill(pid, 0)
    except OSError:
        alive = False

    if not alive:
        print(f"PID {pid} not running, cleaning up")
        pid_file.unlink(missing_ok=True)
        return

    # Send termination signal
    if os.name == "nt":
        import subprocess
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        os.kill(pid, signal.SIGTERM)

    print(f"Sent stop signal to PID {pid}")

    # Wait for process to exit
    for _ in range(30):
        try:
            os.kill(pid, 0)
            time.sleep(0.1)
        except OSError:
            break

    if pid_file.exists():
        pid_file.unlink(missing_ok=True)
    print("Daemon stopped")


def _start_daemon(engine, host: str, port: int, pid_file: Path,
                   tls_cert: str | None = None, tls_key: str | None = None):
    """Start REST server as a background daemon."""
    import os
    import sys
    import subprocess

    tls_args = ""
    if tls_cert and tls_key:
        tls_args = f", tls_cert='{tls_cert}', tls_key='{tls_key}'"

    if os.name == "nt":
        # Windows: launch detached subprocess
        cmd = [
            sys.executable, "-c",
            (
                f"import os, sys; sys.stdin = open(os.devnull); "
                f"Path('{pid_file}').write_text(str(os.getpid())); "
                f"from memorius.rest_server import run_rest_server; "
                f"from memorius.vault import VaultEngine; "
                f"from memorius.config import load_config; "
                f"e = VaultEngine(load_config()); "
                f"run_rest_server(e, host='{host}', port={port}{tls_args})"
            ),
        ]
        proc = subprocess.Popen(
            cmd,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(proc.pid))
        print(f"Daemon started (PID {proc.pid})")
    else:
        # Unix: double-fork
        pid = os.fork()
        if pid > 0:
            print(f"Daemon started (PID {pid})")
            return

        os.setsid()

        pid = os.fork()
        if pid > 0:
            sys.exit(0)

        # Redirect stdio
        sys.stdin = open(os.devnull, "r")
        sys.stdout = open(os.devnull, "w")
        sys.stderr = open(os.devnull, "w")

        # Write PID file
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()))

        import atexit
        def _cleanup():
            pid_file.unlink(missing_ok=True)
        atexit.register(_cleanup)

        import signal
        signal.signal(signal.SIGHUP, signal.SIG_IGN)

        from memorius.rest_server import run_rest_server
        run_rest_server(engine, host=host, port=port)


def cmd_config(engine, args, config):
    """Show current configuration."""
    if args.path:
        path = DEFAULT_CONFIG_PATH
        print(path)
        print(f"  Exists: {path.exists()}")
        return
    print(json.dumps(config, indent=2, default=str))


def cmd_obsidian(engine, args, config):
    """Dispatch obsidian subcommands."""
    from memorius.cli.obsidian import dispatch
    dispatch(engine, args, config)


# ── New v0.2.0 commands ──


def cmd_consolidate(engine, args, config):
    """Consolidate similar memories."""
    print("Consolidating memories...")
    result = engine.consolidate(
        vault=args.vault,
        similarity_threshold=args.threshold,
        dry_run=args.dry_run,
    )
    print(f"  Clusters found:    {result.clusters_found}")
    print(f"  Memories merged:   {result.memories_merged}")
    print(f"  Memories archived: {result.memories_archived}")
    if result.details:
        print("\n  Details:")
        for d in result.details[:5]:
            print(f"    - Cluster of {d['cluster_size']}: {d['insight_preview']}")


def cmd_extract(engine, args, config):
    """Extract memories from a conversation."""
    text = args.text
    if not text and args.file:
        text = Path(args.file).read_text()
    if not text:
        text = sys.stdin.read().strip()
    if not text:
        print("Error: conversation required (--text, <file>, or stdin)")
        return

    print(f"Extracting memories (backend: {args.backend})...")
    memories = engine.extract_memories(
        conversation=text,
        backend=args.backend,
        vault=args.vault,
        shelf=args.shelf,
    )
    print(f"Extracted {len(memories)} memories:")
    for m in memories:
        cat = m.metadata.get("category", "unknown")
        conf = m.metadata.get("confidence", 0)
        print(f"  [{cat}] ({conf:.0%}) {m.content[:80]}")


def cmd_factcheck(engine, args, config):
    """Fact-check a statement."""
    statement = args.statement
    if not statement:
        statement = sys.stdin.read().strip()
    if not statement:
        print("Error: statement required (pass as argument or pipe to stdin)")
        return

    result = engine.check_fact(statement, vault=args.vault)
    icons = {"verified": "✅", "contradicted": "❌", "uncertain": "⚠️", "no_match": "❓"}
    icon = icons.get(result.verdict, "❓")
    print(f"{icon} {result.verdict.upper()}")
    print(f"  Statement: {result.statement}")
    print(f"  Confidence: {result.confidence:.0%}")
    print(f"  {result.explanation}")
    if result.contradicting_memories:
        print("  Contradicting memories:")
        for m in result.contradicting_memories:
            print(f"    - [{m['vault']}/{m['shelf']}] {m['content'][:100]}")

    # Web cross-check when the vault can't settle the claim.
    if result.verdict in ("uncertain", "no_match") and web_fallback_enabled(args, config):
        from memorius.web_search import get_web_provider
        provider = get_web_provider(config)
        if provider:
            web = provider.search(
                result.statement,
                max_results=config.get("retrieval", {}).get("web_max_results", 5),
            )
            if web:
                print("  Web cross-check:")
                for r in web[:3]:
                    print(f"    - {r.title}: {r.url}")


def cmd_web(engine, args, config):
    """Search the internet (web fallback primitive)."""
    from memorius.web_search import get_web_provider

    query = args.query
    if not query:
        query = sys.stdin.read().strip()
    if not query:
        print("Error: query required (pass as argument or pipe to stdin)")
        return

    provider = get_web_provider(config, provider=args.provider)
    if not provider:
        print("Error: no web provider available")
        return

    results = provider.search(query, max_results=args.max)
    print(f'Web search: "{query}"')
    print(f"Results: {len(results)}")
    print()
    for i, r in enumerate(results, 1):
        print(f"{i}. {r.title}")
        print(f"   {r.url}")
        if r.snippet:
            print(f"   {r.snippet[:200]}")


def cmd_context(engine, args, config):
    """Get memory context for injection."""
    query = args.query
    if not query:
        query = sys.stdin.read().strip()
    if not query:
        print("Error: query required (pass as argument or pipe to stdin)")
        return

    context = engine.get_context(query, vault=args.vault, max_items=args.max)
    if context:
        print(context)
    elif web_fallback_enabled(args, config):
        from memorius.web_search import get_web_provider
        provider = get_web_provider(config)
        if provider:
            web = provider.search(
                query,
                max_results=config.get("retrieval", {}).get("web_max_results", 5),
            )
            if web:
                print("No matching memories. Web results (from internet):")
                for r in web:
                    print(f"- {r.title}")
                    print(f"  {r.url}")
                    if r.snippet:
                        print(f"  {r.snippet[:160]}")
            else:
                print("No relevant memories or web results found.")
    else:
        print("No relevant memories found.")


def cmd_profile(engine, args, config):
    """Build session memory profile."""
    session_id = args.session_id
    if not session_id:
        session_id = input("Session ID: ").strip()
    if not session_id:
        print("Error: session_id required")
        return

    from memorius.session import format_profile_for_context
    profile = engine.get_session_profile(session_id, vault=args.vault)
    print(format_profile_for_context(profile))


def cmd_stats(engine, args, config):
    """Show memory statistics."""
    status = engine.status()
    meta_stats = engine.get_memory_stats()
    graph_stats = engine.get_graph_stats()

    print("  Vault Status:")
    print(f"    Vaults:       {status['vaults']}")
    print(f"    Memories:     {status['memories']}")
    print(f"    Embeddings:   {status['embedding_provider']} (dim={status['embedding_dimension']})")
    print()
    print("  Memory Tracking:")
    print(f"    Total:        {meta_stats['total']}")
    print(f"    Active:       {meta_stats['active']}")
    print(f"    Archived:     {meta_stats['archived']}")
    if meta_stats.get('by_vault'):
        print("    By vault:")
        for vault, count in meta_stats['by_vault'].items():
            print(f"      {vault}: {count}")
    print()
    print("  Knowledge Graph:")
    print(f"    Nodes:        {graph_stats.get('unique_nodes', 0)}")
    print(f"    Edges:        {graph_stats.get('total_edges', 0)}")
    relations = graph_stats.get('relations', {})
    if relations:
        print("    Relations:")
        for rel, count in relations.items():
            print(f"      {rel}: {count}")


def cmd_get(engine, args, config):
    """Get a single memory by ID."""
    from memorius.validation import validate_memory_id as _vid
    try:
        memory_id = _vid(args.memory_id)
    except ValueError as e:
        print(f"Error: {e}")
        return
    mem = engine.get_memory(memory_id)
    if mem is None:
        print(f"Error: memory not found: {memory_id}")
        return
    if getattr(args, "output_json", False):
        d = mem.to_dict()
        d.pop("vector", None)
        print(json.dumps(d, indent=2))
    else:
        print(f"ID:      {mem.id}")
        print(f"Path:    {mem.vault}/{mem.shelf}/{mem.folder}/{mem.note}")
        print(f"Created: {mem.created_at or 'N/A'}")
        print(f"Updated: {mem.updated_at or 'N/A'}")
        print(f"\n{mem.content}")


def cmd_update(engine, args, config):
    """Update a memory's content and/or metadata."""
    from memorius.validation import validate_memory_id as _vid
    try:
        memory_id = _vid(args.memory_id)
    except ValueError as e:
        print(f"Error: {e}")
        return
    content = args.content
    metadata = None
    if args.metadata:
        try:
            metadata = json.loads(args.metadata)
        except json.JSONDecodeError as e:
            print(f"Error: invalid JSON for --metadata: {e}")
            return
    if content is None and metadata is None:
        print("Error: specify --content and/or --metadata to update")
        return
    mem = engine.update_memory(memory_id, content=content, metadata=metadata)
    if mem is None:
        print(f"Error: memory not found: {memory_id}")
        return
    if getattr(args, "output_json", False):
        d = mem.to_dict()
        d.pop("vector", None)
        print(json.dumps(d, indent=2))
    else:
        print(f"Updated: {mem.id}")
        print(f"  Path:    {mem.vault}/{mem.shelf}/{mem.folder}/{mem.note}")
        print(f"  Content: {mem.content[:120]}{'...' if len(mem.content) > 120 else ''}")


def cmd_prune(engine, args, config):
    """Find and archive stale memories."""
    result = engine.prune(
        threshold=args.threshold,
        dry_run=args.dry_run,
        archive=not args.hard_delete,
    )
    if getattr(args, "output_json", False):
        print(json.dumps(result, indent=2))
        return
    if result["count"] == 0:
        print("No stale memories found.")
        return
    label = "Would archive" if result["dry_run"] else "Archived"
    if args.hard_delete:
        label = "Would delete" if result["dry_run"] else "Deleted"
    print(f"{result['count']} stale memor{'y' if result['count'] == 1 else 'ies'} found:")
    for item in result["stale"]:
        preview = (item.get("content") or "")[:100]
        print(f"  [{item['decay_score']:.2f}] {item['id']}  {preview}")
    print(f"\n{label}: {result['archived_count']}")


def cmd_export(engine, args, config):
    """Export vault to JSON or Markdown."""
    from memorius.backup import export_json, export_markdown

    fmt = getattr(args, "format", "json")
    dest = args.dest

    if fmt == "json":
        path = export_json(engine, dest)
        print(f"Exported vault to {path}")
    else:
        path = export_markdown(engine, dest)
        print(f"Exported vault to {path}")


def cmd_import(engine, args, config):
    """Import vault from a JSON export."""
    from memorius.backup import import_json

    merge = not getattr(args, "replace", False)
    stats = import_json(engine, args.src, merge=merge)

    total = sum(stats.values())
    print(f"Import complete ({total} operations):")
    for k, v in stats.items():
        if v:
            print(f"  {k}: {v}")


def cmd_doctor(engine, args, config):
    """Run health checks on the vault."""
    from memorius.doctor import run_checks

    result = run_checks(engine=engine)
    print(result["summary"])
    if result["healthy"]:
        print("\nAll checks passed.")
    else:
        print("\nSome checks reported issues — review above.")


def cmd_list(engine, args, config):
    """List memories with cursor pagination."""
    result = engine.list_memories(
        vault=args.vault, limit=args.limit, with_vectors=False, cursor=args.cursor,
    )
    memories = result["memories"]
    next_cursor = result["next_cursor"]

    if not memories:
        print("No memories found.")
        return

    for m in memories:
        content_preview = (m.content[:80] + "...") if len(m.content or "") > 80 else (m.content or "")
        print(f"  {m.id[:8]}  {m.vault}/{m.shelf}/{m.folder}/{m.note}  {content_preview}")

    if next_cursor:
        print(f"\nNext page: memorius list --limit {args.limit} --cursor \"{next_cursor}\"")


def cmd_delete(engine, args, config):
    """Delete a memory by ID, with validation and confirmation."""
    from memorius.validation import validate_memory_id as _validate_memory_id

    # 1) Validate the ID up front — clear error before any side effect.
    try:
        memory_id = _validate_memory_id(args.memory_id)
    except ValueError as e:
        print(f"Error: {e}")
        return

    # 2) Existence + location so we can show the user exactly what they're deleting.
    meta = engine.meta.get_memory_meta(memory_id)
    if not meta:
        print(f"Error: memory not found: {memory_id}")
        return

    path = f"{meta['vault']}/{meta['shelf']}/{meta['folder']}/{meta['note']}"
    preview = (meta["content"] or "").replace("\n", " ").strip()
    if len(preview) > 120:
        preview = preview[:117] + "..."

    # 3) Dry-run: show what would be deleted, change nothing.
    if args.dry_run:
        print(f"[dry-run] Would delete: {memory_id}")
        print(f"  Path:    {path}")
        print(f"  Content: {preview}")
        return

    # 4) Confirmation gate (skipped with --yes). Non-interactive input => abort.
    if not args.yes:
        try:
            ans = input(
                f"Delete memory {memory_id} at {path}?\n"
                f'  "{preview}"\n'
                f"Are you sure? [y/N] "
            ).strip().lower()
        except EOFError:
            print("\nAborted (no confirmation).")
            return
        if ans not in ("y", "yes"):
            print("Aborted.")
            return

    # 5) Delete (engine re-validates and scopes to the memory's real location).
    result = engine.delete(memory_id, vault=args.vault, shelf=args.shelf)
    if result["deleted"]:
        print(f"Deleted: {memory_id}")
        print(f"  Path: {path}")
    else:
        print(f"Nothing deleted (found={result['found']}).")


if __name__ == "__main__":
    main()
