"""Configuration loading for memorius — YAML config with env var overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_DIR = Path.home() / ".memorius"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.yaml"

DEFAULT_CONFIG_YAML = """
# memorius configuration
# Path: ~/.memorius/config.yaml

storage:
  type: chroma  # chroma | sqlite-vec
  path: ~/.memorius/data

embeddings:
  provider: chroma-default  # chroma-default | sentence-transformers | openai
  model: all-MiniLM-L6-v2
  # openai:
  #   api_key: ...
  #   model: text-embedding-3-small

server:
  mcp_port: 8911
  rest_port: 8912
  host: "127.0.0.1"

vault:
  default: "main"
  max_note_size: 1000

hooks:
  enabled: true
  config: ~/.memorius/hooks.yaml

retrieval:
  web_fallback: false      # opt-in: augment thin local recall with web (local-first / privacy)
  web_provider: duckduckgo  # duckduckgo (keyless) | tavily (keyed) | mock (tests)
  tavily_api_key: null      # or set TAVILY_API_KEY env var
  web_min_results: 1       # if ZERO local hits, fall back to web
  web_max_results: 5       # max web results to return
"""


def get_config() -> dict[str, Any]:
    """Return default config with env overrides (no file I/O)."""
    config = _default_config()
    _apply_env_overrides(config)
    _ensure_defaults(config)
    return config


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load config from YAML file, merging with env var overrides.

    Env var overrides (prefixed with MEMORIUS_):
      MEMORIUS_STORAGE_PATH     → storage.path
      MEMORIUS_EMBEDDINGS_PROVIDER → embeddings.provider
      MEMORIUS_OPENAI_API_KEY   → embeddings.openai.api_key
      MEMORIUS_MCP_PORT         → server.mcp_port
      MEMORIUS_REST_PORT        → server.rest_port
      MEMORIUS_HOST             → server.host
    """
    import yaml

    config_path = Path(path or _find_config()).expanduser()

    if config_path.exists():
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = _default_config()

    _apply_env_overrides(config)
    _ensure_defaults(config)
    _validate_secrets(config)
    return config


def _find_config() -> Path:
    """Find config file: cwd ./memorius.yaml, then ~/.memorius/config.yaml."""
    cwd_config = Path.cwd() / "memorius.yaml"
    if cwd_config.exists():
        return cwd_config
    return DEFAULT_CONFIG_PATH


def _default_config() -> dict[str, Any]:
    import yaml
    return yaml.safe_load(DEFAULT_CONFIG_YAML)


def _ensure_defaults(config: dict[str, Any]):
    """Fill in missing keys with defaults."""
    storage = config.setdefault("storage", {})
    storage.setdefault("type", "chroma")
    storage.setdefault("path", "~/.memorius/data")

    embeddings = config.setdefault("embeddings", {})
    embeddings.setdefault("provider", "chroma-default")
    embeddings.setdefault("model", "all-MiniLM-L6-v2")

    server = config.setdefault("server", {})
    server.setdefault("mcp_port", 8911)
    server.setdefault("rest_port", 8912)
    server.setdefault("host", "127.0.0.1")

    vault_cfg = config.setdefault("vault", {})
    vault_cfg.setdefault("default", "main")
    vault_cfg.setdefault("max_note_size", 1000)

    retrieval = config.setdefault("retrieval", {})
    retrieval.setdefault("web_fallback", False)
    retrieval.setdefault("web_provider", "duckduckgo")
    retrieval.setdefault("tavily_api_key", None)
    retrieval.setdefault("web_min_results", 1)
    retrieval.setdefault("web_max_results", 5)

    hooks = config.setdefault("hooks", {})
    hooks.setdefault("enabled", True)
    hooks.setdefault("config", "~/.memorius/hooks.yaml")

    consolidation = config.setdefault("consolidation", {})
    consolidation.setdefault("enabled", False)
    consolidation.setdefault("interval_seconds", 3600)
    consolidation.setdefault("dedup_threshold", 0.92)
    consolidation.setdefault("contradiction_check", True)
    consolidation.setdefault("max_consolidations_per_run", 100)
    consolidation.setdefault("auto_prune", True)

    # Vector store optimization options
    vector_optimization = config.setdefault("vector_optimization", {})
    vector_optimization.setdefault("enable_hnsw_optimization", False)
    vector_optimization.setdefault("hnsw_ef_construction", 100)
    vector_optimization.setdefault("hnsw_ef_search", 100)
    vector_optimization.setdefault("hnsw_max_m", 16)


def _apply_env_overrides(config: dict[str, Any]):
    """Override config values from environment variables."""
    overrides = {
        "MEMORIUS_STORAGE_PATH": ("storage", "path"),
        "MEMORIUS_EMBEDDINGS_PROVIDER": ("embeddings", "provider"),
        "MEMORIUS_MCP_PORT": ("server", "mcp_port"),
        "MEMORIUS_REST_PORT": ("server", "rest_port"),
        "MEMORIUS_HOST": ("server", "host"),
        "MEMORIUS_DEFAULT_VAULT": ("vault", "default"),
        "MEMORIUS_WEB_FALLBACK": ("retrieval", "web_fallback"),
        "MEMORIUS_WEB_PROVIDER": ("retrieval", "web_provider"),
        "MEMORIUS_TAVILY_API_KEY": ("retrieval", "tavily_api_key"),
    }
    for env_key, (section, key) in overrides.items():
        val = os.environ.get(env_key)
        if val is not None:
            config.setdefault(section, {})[key] = _coerce(val)

    # Special handling for OpenAI key
    openai_key = os.environ.get("MEMORIUS_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if openai_key:
        emb = config.setdefault("embeddings", {})
        emb.setdefault("openai", {})["api_key"] = openai_key


def _coerce(val: str) -> int | bool | str:
    """Coerce string to int, bool, or leave as string."""
    if val.lower() in ("true", "yes", "1"):
        return True
    if val.lower() in ("false", "no", "0"):
        return False
    try:
        return int(val)
    except ValueError:
        return val

def _validate_secrets(config):
    """Validate that required secrets are present and strong."""
    # Weak secrets list - common default/weak values
    WEAK_SECRETS = {
        "",
        "changeme",
        "password",
        "123456",
        "admin",
        "secret",
        "token",
        "key",
    }
    
    # Check OpenAI API key if using openai embeddings provider
    embeddings_provider = config.get('embeddings', {}).get('provider')
    if embeddings_provider == 'openai':
        openai_key = config.get('embeddings', {}).get('openai', {}).get('api_key')
        if openai_key is not None:
            openai_key = str(openai_key)
        if not openai_key:
            raise ValueError("Missing OpenAI API key. Set MEMORIUS_OPENAI_API_KEY or OPENAI_API_KEY environment variable.")
        if openai_key in WEAK_SECRETS:
            raise ValueError("Weak OpenAI API key detected. Please use a strong, non-default key.")
        # Optional: check minimum length
        if len(openai_key) < 16:
            raise ValueError("OpenAI API key too short. Minimum length is 16 characters.")
    
    # Check Tavily API key if using tavily web provider
    web_provider = config.get('retrieval', {}).get('web_provider')
    if web_provider == 'tavily':
        tavily_key = config.get('retrieval', {}).get('tavily_api_key')
        if tavily_key is not None:
            tavily_key = str(tavily_key)
        if not tavily_key:
            raise ValueError("Missing Tavily API key. Set TAVILY_API_KEY or MEMORIUS_TAVILY_API_KEY environment variable.")
        if tavily_key in WEAK_SECRETS:
            raise ValueError("Weak Tavily API key detected. Please use a strong, non-default key.")
        if len(tavily_key) < 16:
            raise ValueError("Tavily API key too short. Minimum length is 16 characters.")
