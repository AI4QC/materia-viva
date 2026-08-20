#!/usr/bin/env bash
# Wait for finalize_all.sh to finish, then audit every source for completeness.
# Self-chaining on purpose: it must survive the agent session that launched it.
#   setsid nohup bash scripts/properties/verify_after_finalize.sh &
set -u
cd "$(dirname "$0")/../.."
P=/path/to/user/anaconda3/envs/matgenbench-py310/bin/python
LOGS=data/props_work/_logs
OUT=/tmp/local-workspace
mkdir -p "$LOGS" "$OUT"
rm -f "$LOGS/verify-complete.marker"
echo "verify supervisor started $(date)" >> "$LOGS/chain.log"

# Wait for the finalize chain: either its completion marker appears or the
# process is gone (a killed chain must not leave us waiting forever).
while true; do
  [ -f "$LOGS/finalize-complete.marker" ] && break
  if ! pgrep -f "finalize_all.sh" > /dev/null; then
    echo "verify: finalize process gone without marker $(date)" >> "$LOGS/chain.log"
    break
  fi
  sleep 120
done
echo "verify: finalize clear, auditing $(date)" >> "$LOGS/chain.log"

# Full audit including the field-coverage scan of every staging file.
$P scripts/properties/verify_complete.py --json "$OUT/verify-complete.json" \
    > "$OUT/verify-complete.txt" 2>&1
echo "$?" > "$LOGS/verify-complete.marker"

# Fresh summary table for the docs, regenerated from the final index.
$P scripts/properties/summarize.py > "$OUT/summary-complete.md" 2>/dev/null

echo "verify supervisor finished $(date)" >> "$LOGS/chain.log"
