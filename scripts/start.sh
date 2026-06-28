#!/bin/bash
# GrowMate V2 Startup Script
# Orchestrates: Tailscale check -> agent.py
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[start.sh] Checking Tailscale..."
if ! tailscale status 2>/dev/null; then
    echo "[start.sh] Tailscale not connected, attempting login..."
    tailscale up --accept-dns=false --accept-routes=false &
    sleep 5
fi

echo "[start.sh] Starting agent..."
cd "$SCRIPT_DIR/src"

exec python3 main.py
