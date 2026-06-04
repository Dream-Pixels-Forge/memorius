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
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

from . import (
    AGENT_ADAPTERS,
    GenericAgentAdapter,
    HookEvent,
    HookEventType,
    HookResult,
    detect_agent,
)
from memorius.vault import VaultEngine
from memorius.config import load_config

logger = logging.getLogger("memorius.hooks.engine")

DEFAULT_SAVE_INTERVAL = 15

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

        save_interval = raw.get("save_interval", DEFAULT_SAVE_INTERVAL)
        state_dir = raw.get("state_dir", "~/.memorius/hook_state")
        hooks_raw = raw.get("hooks", {})

        actions: dict[str, list[HookAction]] = {}
        for event_name, event_config in hooks_raw.items():
            action_list = []
            for action in event_config.get("actions", []):
                if isinstance(action, dict):
                    action_list.append(HookAction(
                        type=action.get("type", "unknown"),
                        name=action.get("name", ""),
                        config=action,
                    ))
            actions[event_name] = action_list

        return cls(
            save_interval=save_interval,
            state_dir=state_dir,
            actions=actions,
            raw=raw,
        )

    @classmethod
    def default(cls) -> "HookConfig":
        """Return the default configuration."""
        raw = yaml.safe_load(DEFAULT_CONFIG_YAML)
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "HookConfig":
        """Build from a parsed dict (for in-memory construction)."""
        save_interval = raw.get("save_interval", DEFAULT_SAVE_INTERVAL)
        state_dir = raw.get("state_dir", "~/.memorius/hook_state")
        hooks_raw = raw.get("hooks", {})

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
        self._engine: VaultEngine | None = None

    def _get_engine(self) -> VaultEngine:
        """Lazy-init the VaultEngine from config."""
        if self._engine is None:
            cfg = load_config()
            self._engine = VaultEngine(cfg)
        return self._engine

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
            self.state_manager.save_checkpoint(event.session_id, int(time.time()))

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

    def _build_context(self, event: HookEvent) -> dict[str, Any]:
        context = {
            "session_id": event.session_id,
            "agent_name": event.agent_name,
            "event_type": event.event_type.value,
            "save_interval": str(self.config.save_interval),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if event.transcript_path:
            transcript_path = Path(event.transcript_path)
            context["transcript_path"] = str(transcript_path)
            context["transcript_dir"] = str(transcript_path.parent)
            context["transcript_name"] = transcript_path.name
        else:
            context["transcript_path"] = ""
            context["transcript_dir"] = ""
            context["transcript_name"] = ""

        if event.project_dir:
            context["project_dir"] = event.project_dir
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

        synchronous = action.config.get("synchronous", False)
        engine = self._get_engine()

        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace")
            else:
                # Directory mode: mine all transcript files in dir
                text = ""
                for f in sorted(path.glob("*.txt")) + sorted(path.glob("*.md")) + sorted(path.glob("*.json")):
                    text += f.read_text(encoding="utf-8", errors="replace") + "\n"

            if synchronous:
                memories = engine.mine(text=text, vault="main")
                return {
                    "action": action.name,
                    "status": "done",
                    "memory_count": len(memories),
                    "memory_ids": [m.id for m in memories],
                }
            else:
                # Fire and forget — still synchronous here since engine uses
                # ChromaDB which is fast; no subprocess needed
                memories = engine.mine(text=text, vault="main")
                return {
                    "action": action.name,
                    "status": "done",
                    "memory_count": len(memories),
                    "dispatched": True,
                }
        except Exception as e:
            return {"action": action.name, "status": "error", "error": str(e)}

    def _action_diary(self, action: HookAction, event: HookEvent, context: dict) -> dict:
        """Write a diary entry via VaultEngine directly."""
        message_template = action.config.get("message", "Hook event: {event_type}")
        message = self._format_template(message_template, context)
        engine = self._get_engine()

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
        cmd_template = action.config.get("command", "")
        cmd = self._format_template(cmd_template, context)

        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=60
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
        url_template = action.config.get("url", "")
        url = self._format_template(url_template, context)
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
