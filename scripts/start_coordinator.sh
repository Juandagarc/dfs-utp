#!/usr/bin/env bash
# Run on Host A. Uses config/nodes.json (edit the node IPs first).
cd "$(dirname "$0")/.."
PORT="${PORT:-8000}"
echo "Coordinator listening on 0.0.0.0:$PORT  (dashboard: http://<this-ip>:$PORT)"
exec python3 -m uvicorn coordinator.main:app --host 0.0.0.0 --port "$PORT"
