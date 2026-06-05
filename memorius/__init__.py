"""memorius — self-contained memory vault for any AI agent.

Architecture:

  Storage Layer:
    chroma_db:     Vector store for semantic search (ChromaDB)
    sqlite_store:  Metadata store for vaults, shelves, folders, notes, and diaries (SQLite)
  Hierarchy:       Vault > Shelf > Folder > Note

  Vault Layer:
    vault:    Vault > Shelf > Folder > Note hierarchy
    diary:    Session diary entries with timestamps
    mine:     Extract memories from conversations/transcripts
    search:   Multi-modal search (vector + metadata + temporal)

  Server Layer:
    mcp:      MCP protocol server (primary interface for tool-calling agents)
    rest:     FastAPI REST server (alternative interface for web/curl)

  Integration Layer:
    hooks:       Agent-agnostic hook lifecycle system
    plugin_gen:  Per-agent plugin manifest generator
    normalizers: Conversation format importers (Discord, Telegram, WhatsApp)

  CLI Layer:
    memorius:  Main CLI — init, mine, search, diary, status, serve, hook
"""

__version__ = "0.2.0"
