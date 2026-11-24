#!/usr/bin/env bash
set -euo pipefail

LOG="/tmp/lip_server.log"
PORT=8000
MODEL="gemma4:26b"

cmd_stop() {
  pkill -f "uvicorn server:app" 2>/dev/null || true
  PIDS=$(lsof -ti :"$PORT" 2>/dev/null || true)
  if [ -n "$PIDS" ]; then
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
  fi
  sleep 1
  echo "Stopped uvicorn (port $PORT cleared)."
}

cmd_start() {
  cmd_stop >/dev/null 2>&1 || true
  .venv/bin/uvicorn server:app --host 0.0.0.0 --port "$PORT" --reload >"$LOG" 2>&1 &
  sleep 2
  if curl -sf "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    echo "Started LIP on http://127.0.0.1:$PORT/ (logs: $LOG)"
  else
    echo "uvicorn started, checking logs:"
    tail -n 15 "$LOG"
  fi
}

cmd_status() {
  echo "=== LIP Stack Status ==="
  lsof -i :"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && echo "uvicorn (:$PORT):   RUNNING" || echo "uvicorn (:$PORT):   STOPPED"
  curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && echo "Ollama (:11434):   RUNNING" || echo "Ollama (:11434):   STOPPED"
  lsof -i :6379 -sTCP:LISTEN >/dev/null 2>&1 && echo "FalkorDB (:6379): RUNNING" || echo "FalkorDB (:6379):  STOPPED"
}

cmd_warm() {
  echo "Warming $MODEL in Ollama..."
  curl -sf http://127.0.0.1:11434/api/generate \
    -d "{\"model\":\"$MODEL\",\"prompt\":\"Ready.\",\"stream\":false}" >/dev/null
  echo "$MODEL is warm and ready."
}

case "${1:-status}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  restart) cmd_start ;;
  status)  cmd_status ;;
  warm)    cmd_warm ;;
  logs)    tail -f "$LOG" ;;
  *)       echo "Usage: ./lip.sh {start|stop|restart|status|warm|logs}";;
esac