#!/bin/bash
if ! curl -s http://localhost:8000/api/health >/dev/null 2>&1; then
  echo "Starting Longevity Intelligence Platform on port 8000..."
  .venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000 >/tmp/lip_server.log 2>&1 &
  SERVER_PID=$!
  trap "kill $SERVER_PID 2>/dev/null" EXIT
  sleep 2
fi

./ngrok http --url=eatery-purist-arbitrary.ngrok-free.dev 8000
