#!/usr/bin/env bash
# DEVELOPMENT ONLY - runs all 4 components on THIS machine to test the code.
# The lab guide states this is NOT a valid final deployment (section 3).
cd "$(dirname "$0")/.."
mkdir -p logs
for i in 1 2 3; do
  NODE_ID=node$i STORAGE_DIR=./storage/node$i python3 -m uvicorn node.main:app --port 800$i > logs/node$i.log 2>&1 &
  echo "node$i pid $!"
done
DFS_CONFIG=config/nodes.local.json DFS_METADATA=./storage/metadata.local.json \
  python3 -m uvicorn coordinator.main:app --port 8000 > logs/coordinator.log 2>&1 &
echo "coordinator pid $!  ->  http://127.0.0.1:8000"
echo "Stop everything with:  pkill -f 'uvicorn (node|coordinator).main'"
