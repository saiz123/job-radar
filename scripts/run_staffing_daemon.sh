#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p state
while true; do
  echo "[$(date -u +%FT%TZ)] staffing loop start" >> state/staffing_daemon.log
  python3 scripts/v3_staffing_loop.py >> state/staffing_daemon.log 2>&1 || true
  echo "[$(date -u +%FT%TZ)] staffing loop sleep" >> state/staffing_daemon.log
  sleep 900
done
