"""
Hook Lifecycle Engine — reads declarative config, executes on normalized events.
Uses memorius VaultEngine directly (no shelling out to external CLI).

Config format (~/.memorius/hooks.yaml or --config):

  hooks:
    session_start:
      actions:
        - mine:
            mode: convos
            path: "$transcript_dir"
        - diary: "Session started: $session_id"

    session_stop:
      actions:
        - mine:
            mode: convos
            path: "$transcript_dir"
        - maybe_diary:
            threshold: 15
            message: "Session checkpoint: $session_id"

    pre_compress:
      actions:
        - mine:
            mode: convos
            path: "$transcript_dir"
            synchronous: true
        - diary: "Pre-compression save: $session_id"
"""

from __future__ import annotations

import json
import logging
import re
import socket
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from . import (
    HookEvent,
    HookResult,
)
from memorius.vault import VaultEngine
from memorius.config import load_config

logger = logging.getLogger("memorius.hooks.engine")

DEFAULT_SAVE_INTERVAL = 15


def _substitute_templates(obj, subs: dict[str, str], _depth: int = 0):
    """Recursively replace {key} placeholders with string values in a nested structure.

    Walks dicts, lists, and scalars. Non-string scalars are passed through
    unchanged. Substitution is done at config-load time so action configs
    can reference top-level scalars like {save_interval}.

    Args:
        _depth: Recursion depth guard to prevent infinite substitution loops
                (e.g. if a value contains its own key placeholder).
    """
    if _depth > 10:
        return obj
    if isinstance(obj, dict):
        return {k: _substitute_templates(v, subs, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute_templates(v, subs, _depth + 1) for v in obj]
    if isinstance(obj, str):
        out = obj
        for key, val in subs.items():
            out = out.replace("{" + key + "}", val)
        return out
    return obj


def _sanitize_template_value(value: str) -> str:
    """Sanitize a value before it's used in a command or URL template.

    Strips shell metacharacters, null bytes, and control characters
    to prevent injection via template substitution.
    """
    # Remove null bytes
    value = value.replace("\x00", "")
    # Remove control characters except newline and tab
    value = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    return value


DEFAULT_CONFIG_YAML = """
# Memorius Universal Hook Lifecycle Configuration
# One declarative config for every AI agent.

save_interval: 15

state_dir: "~/.memorius/hook_state"

hooks:
  session_start:
    actions:
      - name: log_session
        type: log
        message: "Session started: {session_id}"

  session_stop:
    actions:
      - name: mine_conversation
        type: mine_dir
        path_var: transcript_dir
        mode: convos
        background: true
      - name: check_diary
        type: conditional_diary
        interval_exchanges: "{save_interval}"

  pre_compress:
    actions:
      - name: mine_conversation_sync
        type: mine_dir
        path_var: transcript_dir
        mode: convos
        synchronous: true
      - name: force_diary
        type: diary
        message: "Pre-compression checkpoint for session {session_id}"
"""


@dataclass
class HookAction:
    """A single action to execute for a hook event."""
    type: str  # mine_dir, diary, conditional_diary, command, log, webhook
    name: str = ""
    config: dict = field(default_factory=dict)


@dataclass
class HookConfig:
    """Complete hook lifecycle configuration."""
    save_interval: int = DEFAULT_SAVE_INTERVAL
    state_dir: str = "~/.memorius/hook_state"
    allow_command_hooks: bool = False  # explicit opt-in required for command action type
    actions: dict[str, list[HookAction]] = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "HookConfig":
        """Load configuration from a YAML file."""
        path = Path(path).expanduser()
        if not path.exists():
            logger.warning(f"Config file not found: {path}, using defaults")
            return cls.default()

        with open(path) as f:
            raw = yaml.safe_load(f) or {}

        return cls.from_dict(raw)

    @classmethod
    def default(cls) -> "HookConfig":
        """Return the default configuration."""
        raw = yaml.safe_load(DEFAULT_CONFIG_YAML)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "HookConfig":
        """Build from a parsed dict (for in-memory construction)."""
        save_interval = int(raw.get("save_interval", DEFAULT_SAVE_INTERVAL))
        state_dir = raw.get("state_dir", "~/.memorius/hook_state")
        allow_command_hooks = bool(raw.get("allow_command_hooks", False))
        hooks_raw = raw.get("hooks", {})

        # Template substitution is done once at config load so that action
        # configs can reference top-level scalars like {save_interval}
        # without each action re-running the format pass. See issue:
        # conditional_diary crashed on the default config because
        # interval_exchanges: "{save_interval}" stayed a literal string.
        subs = {"save_interval": str(save_interval)}
        hooks_raw = _substitute_templates(hooks_raw, subs)

        actions: dict[str, list[HookAction]] = {}
        for event_name, event_config in hooks_raw.items():
            action_list = []
            for action in event_config.get("actions", []):
                if isinstance(action, dict):
                    action_list.append(HookAction(
                        type=action.get("type", "unknown"),
                        name=action.get("name", action.get("type", "")),
                        config=action,
                    ))
            actions[event_name] = action_list

        return cls(
            save_interval=save_interval,
            state_dir=state_dir,
            allow_command_hooks=allow_command_hooks,
            actions=actions,
            raw=raw,
        )


class HookStateManager:
    """Tracks save progress per session to implement the interval check."""

    def __init__(self, state_dir: str | Path):
        self.state_dir = Path(state_dir).expanduser()
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def _state_path(self, session_id: str) -> Path:
        safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', session_id)[:128]
        return self.state_dir / f"{safe_id}_state.json"

    def get_exchange_count(self, session_id: str) -> int:
        state_path = self._state_path(session_id)
        if state_path.exists():
            try:
                data = json.loads(state_path.read_text())
                return data.get("exchange_count", 0)
            except (json.JSONDecodeError, OSError):
                return 0
        return 0

    def save_checkpoint(self, session_id: str, exchange_count: int):
        state_path = self._state_path(session_id)
        data = {
            "session_id": session_id,
            "exchange_count": exchange_count,
            "last_save": time.time(),
        }
        state_path.write_text(json.dumps(data, indent=2))

    def should_save(self, session_id: str, exchange_count: int, interval: int) -> bool:
        if interval <= 0:
            return True
        last_count = self.get_exchange_count(session_id)
        return (exchange_count - last_count) >= interval


class HookEngine:
    """The core lifecycle engine — transforms events into actions.
    
    Uses memorius VaultEngine for all storage operations instead of
    shelling out to an external CLI.
    """

    def __init__(self, config: Optional[HookConfig] = None):
        self.config = config or HookConfig.default()
        self.state_manager = HookStateManager(self.config.state_dir)
        self._last_event_time: dict[str, float] = {}
        self._vault: VaultEngine | None = None

    def _get_vault(self) -> VaultEngine:
        """Lazy-init the VaultEngine from config."""
        if self._vault is None:
            cfg = load_config()
            self._vault = VaultEngine(cfg)
        return self._vault

    def process(self, event: HookEvent) -> HookResult:
        """Process a normalized hook event through the lifecycle engine."""
        logger.info(f"Processing {event.event_type.value} from {event.agent_name} (session={event.session_id})")

        event_key = event.event_type.value
        actions = self.config.actions.get(event_key, [])

        if not actions:
            logger.debug(f"No actions configured for event {event_key}")
            return HookResult(action="allow")

        context = self._build_context(event)

        results = []
        should_block = False
        block_reason = None

        for action in actions:
            try:
                result = self._execute_action(action, event, context)
                results.append(result)
                if result.get("block"):
                    should_block = True
                    block_reason = result.get("reason", "Save checkpoint")
            except Exception as e:
                logger.error(f"Action {action.name} failed: {e}")
                results.append({"action": action.name, "error": str(e)})

        if results:
            # Persist a real exchange count so conditional_diary's
            # (exchange_count - last_count) >= interval check works.
            # Preference: agent supplies exchange_count in raw payload,
            # otherwise we count hook events for this session.
            exchange_count = self._resolve_exchange_count(event)
            self.state_manager.save_checkpoint(event.session_id, exchange_count)

        if should_block and event.can_block:
            return HookResult(
                action="block",
                reason=block_reason or "Memorius save checkpoint. Continue after saving.",
                exit_code=0,
                metadata={"actions": results},
            )

        return HookResult(
            action="allow",
            exit_code=0,
            metadata={"actions": results},
        )

    def _resolve_exchange_count(self, event: HookEvent) -> int:
        """Return the running exchange count for this session.

        Agents that report a real exchange_count in their hook payload
        (e.g. Pi, OpenCode) get exact numbers. Agents that don't (most of
        them, today) get a per-session event count that grows by 1 per
        hook event processed. Either way, conditional_diary's interval
        check now works.
        """
        last_count = self.state_manager.get_exchange_count(event.session_id)
        payload_count = event.raw_payload.get("exchange_count")
        if isinstance(payload_count, (int, float)):
            return max(int(payload_count), last_count)
        return last_count + 1

    def _build_context(self, event: HookEvent) -> dict[str, Any]:
        context = {
            "session_id": _sanitize_template_value(event.session_id),
            "agent_name": _sanitize_template_value(event.agent_name),
            "event_type": event.event_type.value,
            "save_interval": str(self.config.save_interval),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if event.transcript_path:
            transcript_path = Path(event.transcript_path)
            context["transcript_path"] = _sanitize_template_value(str(transcript_path))
            context["transcript_dir"] = _sanitize_template_value(str(transcript_path.parent))
            context["transcript_name"] = _sanitize_template_value(transcript_path.name)
        else:
            context["transcript_path"] = ""
            context["transcript_dir"] = ""
            context["transcript_name"] = ""

        if event.project_dir:
            context["project_dir"] = _sanitize_template_value(event.project_dir)
        else:
            context["project_dir"] = ""

        return context

    def _execute_action(self, action: HookAction, event: HookEvent, context: dict) -> dict:
        action_type = action.config.get("type", action.type)
        result = {"action": action.name, "type": action_type}

        if action_type == "mine_dir":
            return self._action_mine_dir(action, event, context)
        elif action_type == "diary":
            return self._action_diary(action, event, context)
        elif action_type == "conditional_diary":
            return self._action_conditional_diary(action, event, context)
        elif action_type == "command":
            return self._action_command(action, event, context)
        elif action_type == "log":
            logger.info(self._format_template(action.config.get("message", ""), context))
            result["status"] = "logged"
        elif action_type == "webhook":
            return self._action_webhook(action, event, context)
        elif action_type == "inject_context":
            return self._action_inject_context(action, event, context)
        elif action_type == "consolidate":
            return self._action_consolidate(action, event, context)
        elif action_type == "factcheck":
            return self._action_factcheck(action, event, context)
        else:
            logger.warning(f"Unknown action type: {action_type}")

        return result

    def _action_mine_dir(self, action: HookAction, event: HookEvent, context: dict) -> dict:
        """Read a transcript file and mine it via VaultEngine directly."""
        path_var = action.config.get("path_var", "transcript_dir")
        target_path = context.get(path_var, context.get("transcript_dir", ""))

        if not target_path or target_path == "":
            return {"action": action.name, "status": "skipped", "reason": f"no path for ${path_var}"}

        path = Path(target_path)
        if not path.exists():
            return {"action": action.name, "status": "skipped", "reason": f"path not found: {path}"}

        vault_cfg = action.config.get("vault", "main")
        engine = self._get_vault()

        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
            else:
                # Directory mode: mine all transcript files in dir
                texts = []
                for f in sorted(path.glob("*.txt")) + sorted(path.glob("*.md")) + sorted(path.glob("*.json")):
                    try:
                        texts.append(f.read_text(encoding="utf-8", errors="replace"))
                    except (OSError, PermissionError) as e:
                        logger.warning(f"Skipping {f.name}: {e}")
                        continue
                text = "\n".join(texts)

            if not text.strip():
                return {"action": action.name, "status": "skipped", "reason": "no content found"}

            memories = engine.mine(text=text, vault=vault)
            return {
                "action": action.name,
                "status": "done",
                "memory_count": len(memories),
                "memory_ids": [m.id for m in memories],
            }
        except Exception as e:
            return {"action": action.name, "status": "error", "error": str(e)}

    def _action_diary(self, action: HookAction, event: HookEvent, context: dict) -> dict:
        """Write a diary entry via VaultEngine directly."""
        message_template = action.config.get("message", "Hook event: {event_type}")
        message = self._format_template(message_template, context)
        engine = self._get_vault()

        try:
            entry = engine.write_diary(
                session_id=event.session_id,
                title=action.name or "Hook triggered",
                summary=message,
                content=event.raw_payload.get("content", json.dumps(event.raw_payload)),
            )
            return {"action": action.name, "status": "done", "diary_id": entry.get("id")}
        except Exception as e:
            return {"action": action.name, "status": "error", "error": str(e)}

    def _action_conditional_diary(self, action: HookAction, event: HookEvent, context: dict) -> dict:
        interval_exchanges = int(action.config.get("interval_exchanges", str(self.config.save_interval)))
        exchange_count = self.state_manager.get_exchange_count(event.session_id)
        if self.state_manager.should_save(event.session_id, exchange_count, interval_exchanges):
            return self._action_diary(action, event, context)
        return {"action": action.name, "status": "skipped", "reason": f"not yet due (next at +{interval_exchanges} exchanges)"}

    def _action_command(self, action: HookAction, event: HookEvent, context: dict) -> dict:
        import shlex

        # Require explicit opt-in — command hooks can run arbitrary binaries
        if not self.config.allow_command_hooks:
            logger.warning(
                "Command hook '%s' skipped: set allow_command_hooks: true in hooks.yaml to enable",
                action.name,
            )
            return {
                "action": action.name,
                "status": "skipped",
                "reason": "command hooks disabled (set allow_command_hooks: true to enable)",
            }

        cmd_template = action.config.get("command", "")
        cmd = self._format_template(cmd_template, context)

        # Validate: reject empty commands
        if not cmd.strip():
            return {"action": action.name, "status": "skipped", "reason": "empty command"}

        try:
            # Use shlex.split() instead of shell=True to prevent injection
            cmd_parts = shlex.split(cmd)
        except ValueError as e:
            return {"action": action.name, "status": "error", "error": f"Invalid command syntax: {e}"}

        try:
            result = subprocess.run(
                cmd_parts, shell=False, capture_output=True, text=True, timeout=60
            )
            return {
                "action": action.name,
                "status": "done" if result.returncode == 0 else "failed",
                "exit_code": result.returncode,
                "stdout": result.stdout[-300:] if result.stdout else "",
            }
        except subprocess.TimeoutExpired:
            return {"action": action.name, "status": "timeout"}
        except Exception as e:
            return {"action": action.name, "status": "error", "error": str(e)}

    def _action_webhook(self, action: HookAction, event: HookEvent, context: dict) -> dict:
        import ipaddress
        from urllib.parse import urlparse

        url_template = action.config.get("url", "")
        url = self._format_template(url_template, context)

        # Validate URL to prevent SSRF
        try:
            parsed = urlparse(url)
        except Exception:
            return {"action": action.name, "status": "error", "error": "Invalid URL"}

        # Only allow http/https schemes
        if parsed.scheme not in ("http", "https"):
            return {"action": action.name, "status": "error", "error": f"URL scheme '{parsed.scheme}' not allowed"}

        hostname = parsed.hostname or ""
        if not hostname:
            return {"action": action.name, "status": "error", "error": "Missing hostname"}

        # Resolve hostname to IPs and check every resolved address.
        # This prevents SSRF via DNS rebinding (e.g. evil.com -> 169.254.169.254).
        blocked_metadata_hosts = ("metadata.google.internal", "instance-data")
        if hostname in blocked_metadata_hosts:
            return {"action": action.name, "status": "error", "error": "Webhook to metadata endpoint is not allowed"}

        try:
            resolved = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror as e:
            return {"action": action.name, "status": "error", "error": f"DNS resolution failed: {e}"}

        for _family, _type, _proto, _canonname, sockaddr in resolved:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                    return {
                        "action": action.name,
                        "status": "error",
                        "error": f"Webhook to private/internal address is not allowed ({ip_str})",
                    }
            except ValueError:
                pass

        payload = event.raw_payload

        try:
            import httpx
            resp = httpx.post(url, json=payload, timeout=10)
            return {
                "action": action.name,
                "status": "done" if resp.is_success else "failed",
                "status_code": resp.status_code,
            }
        except ImportError:
            return {"action": action.name, "status": "error", "error": "httpx not installed"}
        except Exception as e:
            return {"action": action.name, "status": "error", "error": str(e)}

    @staticmethod
    def _format_template(template: str, context: dict) -> str:
        result = template
        for key, value in context.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result

    # ── New v0.2.0 action handlers ──

    def _action_inject_context(self, action: HookAction, event: HookEvent, context: dict) -> dict:
        """Inject relevant memories into context."""
        query_template = action.config.get("query_template", "{session_id}")
        query = self._format_template(query_template, context)
        max_memories = action.config.get("max_memories", 5)

        try:
            engine = self._get_vault()
            context_text = engine.get_context(query, max_items=max_memories)
            return {
                "action": action.name,
                "status": "done",
                "has_context": bool(context_text),
                "context_length": len(context_text),
                "context_preview": context_text[:200] if context_text else "",
            }
        except Exception as e:
            return {"action": action.name, "status": "error", "error": str(e)}

    def _action_consolidate(self, action: HookAction, event: HookEvent, context: dict) -> dict:
        """Run memory consolidation."""
        try:
            engine = self._get_vault()
            threshold = action.config.get("similarity_threshold", 0.80)
            dry_run = action.config.get("dry_run", False)
            result = engine.consolidate(
                similarity_threshold=threshold,
                dry_run=dry_run,
            )
            return {
                "action": action.name,
                "status": "done",
                "clusters_found": result.clusters_found,
                "memories_merged": result.memories_merged,
                "memories_archived": result.memories_archived,
            }
        except Exception as e:
            return {"action": action.name, "status": "error", "error": str(e)}

    def _action_factcheck(self, action: HookAction, event: HookEvent, context: dict) -> dict:
        """Fact-check a statement from the event payload."""
        statement_template = action.config.get("statement_template", "")
        if statement_template:
            statement = self._format_template(statement_template, context)
        else:
            statement = event.raw_payload.get("statement", "")

        if not statement:
            return {"action": action.name, "status": "skipped", "reason": "no statement to check"}

        try:
            engine = self._get_vault()
            result = engine.check_fact(statement)
            return {
                "action": action.name,
                "status": "done",
                "verdict": result.verdict,
                "confidence": result.confidence,
                "explanation": result.explanation,
            }
        except Exception as e:
            return {"action": action.name, "status": "error", "error": str(e)}
