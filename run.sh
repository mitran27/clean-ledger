#!/usr/bin/env bash
# Start the attestation sidecar (:8787) and the app (:8765). Ctrl-C stops both.
cd "$(dirname "$0")"
.venv/bin/uvicorn sidecar.proxy:app --port 8787 & S=$!
.venv/bin/uvicorn app.server:app --port 8765 & A=$!
trap 'kill $S $A 2>/dev/null' INT TERM EXIT
echo "sidecar http://localhost:8787   app http://localhost:8765"
wait
