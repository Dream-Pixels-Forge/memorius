# Security Audit Context - Memorius

## Project Overview
- **Name**: memorius
- **Version**: 0.2.0
- **Type**: Python library/CLI for AI agent memory vault
- **Description**: Self-contained memory vault for any AI agent — vector search, session diaries, and agent-agnostic hooks.

## Architecture
- **Storage Layer**: ChromaDB (vector store), SQLite (metadata)
- **Server Layer**: MCP protocol server, FastAPI REST server
- **Integration Layer**: Agent hooks, plugin generator, conversation normalizers
- **CLI Layer**: memorius, memorius-hook, memorius-plugin-gen, memorius-normalize

## Key Files
- `/memorius/vault.py` - Vault hierarchy management
- `/memorius/graph.py` - Knowledge graph operations
- `/memorius/mcp_server.py` - MCP protocol server
- `/memorius/rest_server.py` - FastAPI REST server
- `/memorius/cli/main.py` - Main CLI entry point
- `/memorius/config.py` - Configuration handling
- `/memorius/session.py` - Session management
- `/memorius/llm_extract.py` - LLM integration for extraction
- `/memorius/embeddings.py` - Embedding operations

## Dependencies
- pyyaml>=6.0
- chromadb>=0.4.0
- httpx>=0.24.0
- Optional: fastapi, uvicorn, pydantic, sse-starlette, sentence-transformers, openai

## Security Concerns to Investigate
1. Input validation in CLI and REST endpoints
2. Authentication/authorization mechanisms
3. Data protection (vault contents, user data)
4. SQL injection risks in SQLite operations
5. XSS vulnerabilities in any web interfaces
6. CSRF protection for REST API
7. Secure handling of API keys and secrets
8. Dependency vulnerabilities
9. File system permissions and access control
10. Remote code execution risks (LLM integration)

## Audit Scope
- Full codebase scan
- Dependency analysis
- Configuration review
- Architecture security patterns
