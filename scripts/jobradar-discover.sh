#!/usr/bin/env bash
set -euo pipefail
set -a
source "${JOBRADAR_ENV_FILE:-$HOME/.hermes/scripts/jobradar.env}"
set +a

: "${JOBRADAR_BASE_URL:?missing JOBRADAR_BASE_URL}"
: "${JOBRADAR_SERVICE_TOKEN:?missing JOBRADAR_SERVICE_TOKEN}"
: "${CAREEROPS_ROOT:?missing CAREEROPS_ROOT}"
: "${NODE_BIN:?missing NODE_BIN}"
: "${JOBRADAR_ROOT:?missing JOBRADAR_ROOT}"
: "${JOBRADAR_DB_PATH:?missing JOBRADAR_DB_PATH}"

scan=$(curl -fsS -X POST "$JOBRADAR_BASE_URL/api/v1/scans" \
  -H "Authorization: Bearer $JOBRADAR_SERVICE_TOKEN" \
  -H "X-JobRadar-Actor: hermes" \
  -H 'Content-Type: application/json' \
  -d '{"mode":"portals","trigger":"cron"}')
scan_id=$(printf '%s' "$scan" | python3 -c 'import sys,json; print(json.load(sys.stdin)["scan_id"])')

cd "$CAREEROPS_ROOT"
history_file="$CAREEROPS_ROOT/data/scan-history.tsv"
before_lines=0
if [ -f "$history_file" ]; then
  before_lines=$(wc -l < "$history_file")
fi

"$NODE_BIN" scan.mjs >> "$CAREEROPS_ROOT/data/scan.log" 2>&1 || echo "warn: scan.mjs failed" >&2

candidates_json=$(python3 "$JOBRADAR_ROOT/scripts/careerops_scan_history_to_jobradar.py" \
  --history-file "$history_file" \
  --db-path "$JOBRADAR_DB_PATH" \
  --fresh-after-lines "$before_lines" \
  --max-backfill 500)

candidate_count=$(printf '%s' "$candidates_json" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))')
payload_file=$(mktemp)
trap 'rm -f "$payload_file"' EXIT
printf '{"candidates":%s}' "$candidates_json" > "$payload_file"
result=$(curl -fsS -X POST "$JOBRADAR_BASE_URL/api/v1/scans/$scan_id/ingest" \
  -H "Authorization: Bearer $JOBRADAR_SERVICE_TOKEN" \
  -H "X-JobRadar-Actor: hermes" \
  -H 'Content-Type: application/json' \
  --data-binary "@$payload_file")

queue_count=$(curl -fsS "$JOBRADAR_BASE_URL/api/v1/jobs/evaluation-queue?limit=8&count_only=1" \
  -H "Authorization: Bearer $JOBRADAR_SERVICE_TOKEN" \
  -H "X-JobRadar-Actor: hermes" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("count",0))')

python3 - <<PY
import json
result = json.loads('''$result''')
result['candidates_submitted'] = int('$candidate_count')
result['evaluation_queue_count'] = int('$queue_count')
print(json.dumps(result, sort_keys=True))
PY

if [ "$queue_count" -gt 0 ]; then
  printf '{"wakeAgent":true,"evaluation_queue_count":%s}\n' "$queue_count"
fi
