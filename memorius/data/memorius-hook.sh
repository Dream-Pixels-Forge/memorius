#!/usr/bin/env bash
# MEMORIUS UNIVERSAL HOOK — Single hook script for ANY AI agent.
#
# Installs as your agent's hook command regardless of agent.
# Auto-detects the agent and forwards to the universal hook lifecycle engine.
#
# Install:
#   ln -s $(which memorius-hook) /path/to/agent/hooks/memorius-hook.sh
#   # or:
#   bash hooks/memorius-hook.sh < event.json

set -euo pipefail

MEMORIUS_HOME="${MEMORIUS_HOME:-$HOME/.memorius}"
CONFIG_DIR="$MEMORIUS_HOME"

# ── Resolve hook engine ──
if command -v memorius-hook &>/dev/null; then
    HOOK_ENGINE="memorius-hook"
elif [ -f "$MEMORIUS_HOME/bin/memorius-hook" ]; then
    HOOK_ENGINE="$MEMORIUS_HOME/bin/memorius-hook"
else
    HOOK_ENGINE="python3 -m memorius.hooks.cli"
fi

# ── Determine hook event ──
# If the script was called with an event name as $1, use that.
# Otherwise try to infer from the calling agent's convention.
EVENT="${1:-}"
if [ -z "$EVENT" ]; then
    # Try to guess from the hook script name (symlink target)
    SCRIPT_NAME=$(basename "$0" .sh)
    case "$SCRIPT_NAME" in
        *stop*)      EVENT="stop" ;;
        *precompact*) EVENT="precompact" ;;
        *precompress*) EVENT="precompress" ;;
        *save*)      EVENT="save" ;;
        *start*)     EVENT="session-start" ;;
        *hook*)      EVENT="stop" ;;  # generic hook.sh → stop
        *)           EVENT="unknown" ;;
    esac
fi

# ── Read stdin ──
INPUT=$(cat)

# ── Run through universal lifecycle engine ──
echo "$INPUT" | $HOOK_ENGINE run --event "$EVENT" --config "$CONFIG_DIR/hooks.yaml"
