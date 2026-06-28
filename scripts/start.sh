#!/bin/bash
# GrowMate V2 Startup Script
# Orchestrates: Tailscale check -> rpicam-vid daemon -> agent.py
set -e

PROJECT_DIR="/home/pi/growmate"

echo "[start.sh] Checking Tailscale..."
if ! tailscale status 2>/dev/null; then
    echo "[start.sh] Tailscale not connected, attempting login..."
    tailscale up --accept-dns=false --accept-routes=false &
    sleep 5
fi

echo "[start.sh] Starting agent..."
cd "$PROJECT_DIR"
exec python3 main.py
