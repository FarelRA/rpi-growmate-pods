#!/bin/bash
# GrowMate V2 Startup Script
# Orchestrates: Tailscale check -> agent.py
set -e

# Resolve project root — works from scripts/ or project root
SELF="$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")"
SELF_DIR="$(dirname "$SELF")"
if [ "$(basename "$SELF_DIR")" = "scripts" ]; then
    PROJECT_ROOT="$(dirname "$SELF_DIR")"
else
    PROJECT_ROOT="$SELF_DIR"
fi

echo "[start.sh] Checking Tailscale..."
if ! tailscale status 2>/dev/null; then
    echo "[start.sh] Tailscale not connected, attempting login..."
    tailscale up --accept-dns=false --accept-routes=false &
    sleep 5
fi

echo "[start.sh] Starting agent..."
cd "$PROJECT_ROOT/src"

exec python3 main.py
