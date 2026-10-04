#!/bin/bash
# Runs the API (:8000) and the UI (:3000) in one container and exits if
# either process dies, so the orchestrator can restart the container.
set -euo pipefail

cd /app/backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --no-server-header &
API_PID=$!

cd /app/web
PORT=3000 HOSTNAME=0.0.0.0 node server.js &
WEB_PID=$!

shutdown() {
  kill -TERM "$API_PID" "$WEB_PID" 2>/dev/null || true
  wait "$API_PID" "$WEB_PID" 2>/dev/null || true
}
trap shutdown SIGTERM SIGINT

set +e
wait -n "$API_PID" "$WEB_PID"
STATUS=$?
set -e
echo "a controller process exited (status $STATUS); stopping" >&2
shutdown
exit "$STATUS"
