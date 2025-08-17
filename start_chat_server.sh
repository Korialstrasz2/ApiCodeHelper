#!/usr/bin/env bash
PORT=8000
while ! python - <<'PY' $PORT
import socket, sys
s=socket.socket()
try:
    s.bind(('127.0.0.1', int(sys.argv[1])))
    s.close()
    sys.exit(0)
except OSError:
    sys.exit(1)
PY
do
  echo "Port $PORT in use, trying next..."
  PORT=$((PORT + 1))
done

echo "Starting server on port $PORT..."
python manage.py runserver $PORT &
SERVER_PID=$!

sleep 3
python -m webbrowser "http://127.0.0.1:$PORT/chat/" >/dev/null 2>&1 &

wait $SERVER_PID
