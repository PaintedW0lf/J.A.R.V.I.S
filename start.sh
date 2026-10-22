#!/bin/bash
# Start Jarvis on this Mac. First run sets everything up (about a minute).
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "Setting up Jarvis for the first time…"
  python3 -m venv .venv
  ./.venv/bin/pip install -q --upgrade pip
  ./.venv/bin/pip install -q -r requirements.txt
fi
echo "Jarvis is running at http://localhost:8765  (press Ctrl+C to stop)"
( sleep 2; open "http://localhost:8765" 2>/dev/null || true ) &
exec ./.venv/bin/uvicorn jarvis.server:app --host 127.0.0.1 --port 8765
