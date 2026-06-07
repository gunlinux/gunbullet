#!/usr/bin/env bash
#
# bench.sh — benchmark the three ASGI /api schema routes with wrk.
#
# Boots the ASGI app (app_asgi), waits until it answers, runs wrk against each
# of /api/pydantic, /api/marshmallow and /api/msgspec, then shuts the server
# down. The three routes return equivalent JSON produced by three different
# validate->serialize pipelines, so this compares the libraries head to head.
#
# Usage:
#   ./bench.sh                 # defaults below
#   DURATION=30s ./bench.sh    # override any knob via env vars
#   WORKERS=4 ./bench.sh       # multi-worker, fairer throughput picture
#   SERVER="granian --interface asgi main:app_asgi" ./bench.sh
#
set -euo pipefail
cd "$(dirname "$0")"

# ---- knobs (override via environment) --------------------------------------
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
DURATION="${DURATION:-15s}"
THREADS="${THREADS:-4}"
CONNECTIONS="${CONNECTIONS:-50}"
WORKERS="${WORKERS:-1}"
# Command used to launch the server, bound to $HOST:$PORT below.
# Both uvicorn and granian accept --host/--port/--workers.
#
# Default is a production-shaped uvicorn: the uvloop event loop and the
# httptools HTTP parser (both from the uvicorn[standard] extra) instead of the
# pure-Python asyncio/h11 fallbacks. Throughput scales with $WORKERS (separate
# processes — uvicorn has no in-process threading model).
SERVER="${SERVER:-uvicorn main:app_asgi --loop uvloop --http httptools}"

ROUTES=(
  "/api/pydantic"
  "/api/marshmallow"
  "/api/marshmallow-ujson"
  "/api/msgspec"
)

# ---- preflight -------------------------------------------------------------
command -v wrk >/dev/null 2>&1 || { echo "error: wrk not found (brew install wrk)" >&2; exit 1; }
command -v uv  >/dev/null 2>&1 || { echo "error: uv not found" >&2; exit 1; }

# Refuse to start if the port is already taken — otherwise our server fails to
# bind, the readiness check hits the *other* process, and we'd benchmark a
# stale server instead of the one we launched.
port_in_use() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v nc >/dev/null 2>&1; then
    nc -z "${HOST}" "${PORT}" >/dev/null 2>&1
  else
    return 1  # can't tell; let the server's own bind error surface
  fi
}
if port_in_use; then
  echo "error: ${HOST}:${PORT} is already in use — stop that server or set PORT=..." >&2
  exit 1
fi

BASE="http://${HOST}:${PORT}"

# ---- boot the server -------------------------------------------------------
echo ">> starting server: uv run ${SERVER} --host ${HOST} --port ${PORT} --workers ${WORKERS}"
# shellcheck disable=SC2086
uv run ${SERVER} --host "${HOST}" --port "${PORT}" --workers "${WORKERS}" >/tmp/bench-server.log 2>&1 &
SERVER_PID=$!

cleanup() {
  echo ">> stopping server (pid ${SERVER_PID})"
  kill "${SERVER_PID}" 2>/dev/null || true
  wait "${SERVER_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ---- wait until it answers --------------------------------------------------
echo ">> waiting for ${BASE} ..."
for i in $(seq 1 50); do
  if curl -fsS -o /dev/null "${BASE}/api/pydantic" 2>/dev/null; then
    echo ">> server is up"
    break
  fi
  if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
    echo "error: server exited during startup; log follows:" >&2
    cat /tmp/bench-server.log >&2
    exit 1
  fi
  sleep 0.2
  if [ "${i}" -eq 50 ]; then
    echo "error: server did not become ready in time" >&2
    cat /tmp/bench-server.log >&2
    exit 1
  fi
done

# ---- run wrk against each route --------------------------------------------
echo
echo "================================================================"
echo " wrk: ${THREADS} threads, ${CONNECTIONS} connections, ${DURATION}"
echo " server: ${SERVER} (${WORKERS} worker(s))"
echo "================================================================"

for route in "${ROUTES[@]}"; do
  echo
  echo "---------------- ${route} ----------------"
  wrk -t"${THREADS}" -c"${CONNECTIONS}" -d"${DURATION}" --latency "${BASE}${route}"
done

echo
echo ">> done"
