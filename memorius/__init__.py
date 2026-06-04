"""memorius — self-contained memory palace for any AI agent.

Architecture:

  Storage Layer:
    chroma_db:     Vector store for semantic search (ChromaDB)
    sqlite_store:  Metadata store for palaces, wings, rooms, drawers (SQLite)
    embeddings:    Abstracted embedding provider (OpenAI, sentence-transformers)

  Palace Layer:
    palace:   Palace > Wing > Room > Drawer knowledge hierarchy
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

__version__ = "0.1.0"
