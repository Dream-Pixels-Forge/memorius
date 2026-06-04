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
  type: chroma  # chroma | sqlite (chroma is always primary for vectors)
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

palace:
  default: "main"
  max_drawer_size: 1000

hooks:
  enabled: true
  config: ~/.memorius/hooks.yaml
"""


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

    palace = config.setdefault("palace", {})
    palace.setdefault("default", "main")
    palace.setdefault("max_drawer_size", 1000)

    hooks = config.setdefault("hooks", {})
    hooks.setdefault("enabled", True)
    hooks.setdefault("config", "~/.memorius/hooks.yaml")


def _apply_env_overrides(config: dict[str, Any]):
    """Override config values from environment variables."""
    overrides = {
        "MEMORIUS_STORAGE_PATH": ("storage", "path"),
        "MEMORIUS_EMBEDDINGS_PROVIDER": ("embeddings", "provider"),
        "MEMORIUS_MCP_PORT": ("server", "mcp_port"),
        "MEMORIUS_REST_PORT": ("server", "rest_port"),
        "MEMORIUS_HOST": ("server", "host"),
        "MEMORIUS_DEFAULT_PALACE": ("palace", "default"),
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


def _coerce(val: str) -> int | str:
    """Coerce string to int if possible, else return as-is."""
    try:
        return int(val)
    except ValueError:
        return val
