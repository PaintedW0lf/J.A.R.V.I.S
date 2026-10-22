#!/bin/bash
# Start Jarvis on this Mac. First run sets everything up (about a minute).
cd "$(dirname "$0")" || exit 1

fail() { echo; echo "Jarvis couldn't start: $1"; echo "Copy the lines above and ask for help."; exit 1; }

# 1. Find a Python 3.10+ interpreter
PY=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || fail "it needs Python 3.10 or newer. Install it with: brew install python  (or from python.org), then run ./start.sh again."

# 2. Create the environment, or rebuild it if it's missing, broken or requirements changed
REQ_HASH=$(shasum requirements.txt | cut -d' ' -f1)
if [ ! -x .venv/bin/python ] || [ "$(cat .venv/.ready 2>/dev/null)" != "$REQ_HASH" ]; then
  echo "Setting up Jarvis (first run or after an update, about a minute)…"
  rm -rf .venv
  "$PY" -m venv .venv || fail "couldn't create the environment with $PY."
  ./.venv/bin/python -m pip install -q --upgrade pip || fail "pip couldn't update."
  ./.venv/bin/python -m pip install -q -r requirements.txt || fail "some packages didn't install. The error is in the lines above."
  echo "$REQ_HASH" > .venv/.ready
fi

# 3. Make sure the port is free
if lsof -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  fail "something is already using port 8765. If Jarvis is already open in your browser, just use that. Otherwise quit the old Jarvis (Ctrl+C in its Terminal window) and try again."
fi

echo "Jarvis is running at http://localhost:8765  (press Ctrl+C to stop)"
( sleep 3; open "http://localhost:8765" 2>/dev/null || true ) &
exec ./.venv/bin/python -m uvicorn jarvis.server:app --host 127.0.0.1 --port 8765
