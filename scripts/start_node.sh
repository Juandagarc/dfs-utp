#!/usr/bin/env bash
# Run on Hosts B, C, D.   Usage: ./scripts/start_node.sh node1 [port]
cd "$(dirname "$0")/.."
export NODE_ID="${1:?usage: start_node.sh <node1|node2|node3> [port]}"
PORT="${2:-8001}"
echo "Storage node $NODE_ID on 0.0.0.0:$PORT, files in ./storage/$NODE_ID"
exec python3 -m uvicorn node.main:app --host 0.0.0.0 --port "$PORT"
