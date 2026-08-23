#!/usr/bin/env bash
# Event stream for the finalize + verify chain: one line per source that
# finishes loading, one per stage marker, one per failure. Exits when the
# verification audit is done or when the chain dies without it.
set -u
cd "$(dirname "$0")/../.."
LOGS=data/props_work/_logs
OUT="${MV_OUT:-data/props_work/_out}"
mkdir -p "$OUT"
STATE=$(mktemp)
CHAINLINES=$(wc -l < "$LOGS/chain.log" 2>/dev/null || echo 0)

# Seed with the load reports that already exist so only new ones are events.
find data/props_work -maxdepth 2 -name load_report.json -newermt '-14 days' \
  -printf '%p %T@\n' 2>/dev/null | sort > "$STATE"

while true; do
  NEW=$(mktemp)
  find data/props_work -maxdepth 2 -name load_report.json -newermt '-14 days' \
    -printf '%p %T@\n' 2>/dev/null | sort > "$NEW"
  comm -13 "$STATE" "$NEW" | while read -r path _; do
    src=$(basename "$(dirname "$path")")
    rows=$(grep -o '"property_rows": [0-9]*' "$path" 2>/dev/null | head -1 | tr -d '"' | awk '{print $2}')
    un=$(grep -o '"props_unmatched": [0-9]*' "$path" 2>/dev/null | head -1 | tr -d '"' | awk '{print $2}')
    echo "loaded $src: ${rows:-?} property rows, ${un:-0} unmatched"
  done
  mv "$NEW" "$STATE"

  # New chain.log lines: stage transitions and explicit failures.
  TOTAL=$(wc -l < "$LOGS/chain.log" 2>/dev/null || echo 0)
  if [ "$TOTAL" -gt "$CHAINLINES" ]; then
    tail -n +$((CHAINLINES + 1)) "$LOGS/chain.log" | sed 's/^/chain: /'
    CHAINLINES=$TOTAL
  fi

  if [ -f "$LOGS/verify-complete.marker" ]; then
    echo "VERIFY DONE (exit $(cat "$LOGS/verify-complete.marker")) — audit at $OUT/verify-complete.txt"
    rm -f "$STATE"
    exit 0
  fi

  # Liveness: any stage of the chain counts. Keep this list in step with the
  # supervisor scripts -- a stale name here reports a false "CHAIN DIED" while
  # the work is in fact running under its successor.
  if ! pgrep -f "finalize_all.sh" > /dev/null \
     && ! pgrep -f "repair_and_verify.sh" > /dev/null \
     && ! pgrep -f "load_new_extractors.sh" > /dev/null \
     && ! pgrep -f "fix_framework_hash_refs.sh" > /dev/null \
     && ! pgrep -f "hmof_chain.sh" > /dev/null \
     && ! pgrep -f "core_mof_chain.sh" > /dev/null \
     && ! pgrep -f "publish_chain.sh" > /dev/null \
     && ! pgrep -f "verify_after_finalize.sh" > /dev/null; then
    echo "CHAIN DIED: no finalize / repair / extractor / verify supervisor is running"
    rm -f "$STATE"
    exit 1
  fi
  sleep 180
done
