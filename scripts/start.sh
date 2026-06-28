#!/bin/bash
# GrowMate V2 Startup Script
# Orchestrates: Tailscale check -> rpicam-vid daemon -> agent.py
set -e

PROJECT_DIR="/home/pi/growmate"

echo "[start.sh] Checking Tailscale..."
tailscale status || tailscale up

echo "[start.sh] Starting camera stream..."
rpicam-vid -t 0 --inline --listen \
  -o tcp://0.0.0.0:8554 \
  --width 640 --height 480 --framerate 15 \
  --bitrate 1000000 --profile baseline --level 3.1 \
  --denoise cdn_off &
RPICAM_PID=$!
sleep 2

echo "[start.sh] Registering stream..."
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "127.0.0.1")
curl -s -X POST "https://growmate.bond/api/v2/stream/register" \
  -H "x-api-key: $DEVICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"deviceId\": \"$DEVICE_ID\", \"streamUrl\": \"tcp://$TAILSCALE_IP:8554\"}" \
  -o /dev/null -w "%{http_code}" || echo "Stream registration failed"

echo "[start.sh] Starting agent..."
cd "$PROJECT_DIR"
exec python3 main.py
