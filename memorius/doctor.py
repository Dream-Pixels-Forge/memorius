"""Health-check diagnostics for a memorius installation.

``memorius doctor`` runs a suite of read-only checks and prints a coloured
summary.  Each check returns ``"ok"`` or a human-readable issue string.

Checks
------
1. Config file parseable + required keys present
2. Storage directory writable
3. ONNX embedding model present
4. memory_meta row count matches Chroma vector count (drift detection)
5. No Chroma collection name > 63 chars
6. Graph table present and edge count > 0 when memory count > 10
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger("memorius.doctor")


def run_checks(engine=None) -> dict[str, Any]:
    """Run all health checks and return a structured report.

    Returns:
        dict with keys ``checks`` (list of check dicts), ``healthy`` (bool),
        and ``summary`` (human-readable string).
    """
    from memorius.config import load_config, DEFAULT_CONFIG_PATH
    from memorius.model_download import is_model_downloaded

    checks: list[dict[str, Any]] = []

    def _add(name: str, status: str, detail: str = ""):
        checks.append({"name": name, "status": status, "detail": detail})

    # 1. Config
    try:
        config = load_config()
        required = ("embeddings", "storage")
        missing = [k for k in required if k not in config]
        if missing:
            _add("config", "warn", f"Missing keys: {', '.join(missing)}")
        else:
            _add("config", "ok")
    except Exception as exc:
        _add("config", "fail", str(exc))
        config = {}

    # 2. Storage directory writable
    storage_cfg = config.get("storage", {})
    storage_path = Path(storage_cfg.get("path", "~/.memorius/data")).expanduser()
    try:
        storage_path.mkdir(parents=True, exist_ok=True)
        test_file = storage_path / ".doctor_write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        _add("storage_dir", "ok", str(storage_path))
    except Exception as exc:
        _add("storage_dir", "fail", str(exc))

    # 3. ONNX model
    try:
        if is_model_downloaded():
            _add("onnx_model", "ok")
        else:
            _add("onnx_model", "warn", "Model not downloaded; run 'memorius setup'")
    except Exception as exc:
        _add("onnx_model", "fail", str(exc))

    # 4–6 require an engine
    if engine is None:
        _add("vector_count_match", "skip", "No engine provided")
        _add("collection_names", "skip", "No engine provided")
        _add("graph_health", "skip", "No engine provided")
    else:
        conn = engine._meta._conn()

        # 4. Row count drift: memory_meta vs Chroma collections
        try:
            meta_count = conn.execute("SELECT COUNT(*) FROM memory_meta").fetchone()[0]
            chroma = engine._vector._lazy_client()
            vector_count = 0
            for col in chroma.list_collections():
                vector_count += col.count()
            if meta_count == vector_count:
                _add("vector_count_match", "ok", f"meta={meta_count}, vectors={vector_count}")
            else:
                _add("vector_count_match", "warn",
                     f"Drift detected: memory_meta={meta_count}, vectors={vector_count}")
        except Exception as exc:
            _add("vector_count_match", "fail", str(exc))

        # 5. Collection name length
        try:
            chroma = engine._vector._lazy_client()
            long_names = []
            for col in chroma.list_collections():
                if len(col.name) > 63:
                    long_names.append(col.name)
            if long_names:
                _add("collection_names", "fail",
                     f"{len(long_names)} collection(s) exceed 63 chars: {long_names[:3]}")
            else:
                _add("collection_names", "ok")
        except Exception as exc:
            _add("collection_names", "fail", str(exc))

        # 6. Graph health
        try:
            conn.execute("SELECT COUNT(*) FROM memory_graph")
            edge_count = conn.execute("SELECT COUNT(*) FROM memory_graph").fetchone()[0]
            meta_count = conn.execute("SELECT COUNT(*) FROM memory_meta").fetchone()[0]
            if meta_count > 10 and edge_count == 0:
                _add("graph_health", "warn",
                     f"{meta_count} memories but 0 graph edges — graph may not be building")
            else:
                _add("graph_health", "ok", f"{edge_count} edges, {meta_count} memories")
        except sqlite3.OperationalError:
            _add("graph_health", "warn", "memory_graph table does not exist yet")
        except Exception as exc:
            _add("graph_health", "fail", str(exc))

    healthy = all(c["status"] in ("ok", "skip") for c in checks)
    lines = []
    icons = {"ok": "+", "warn": "!", "fail": "X", "skip": "-"}
    for c in checks:
        icon = icons.get(c["status"], "?")
        line = f"  [{icon}] {c['name']}: {c['status']}"
        if c["detail"]:
            line += f"  ({c['detail']})"
        lines.append(line)

    summary = "\n".join(lines)
    return {"checks": checks, "healthy": healthy, "summary": summary}
