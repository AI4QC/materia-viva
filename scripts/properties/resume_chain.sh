#!/usr/bin/env bash
# Resume the full property-ingestion chain; every stage is idempotent/resumable.
# Run detached:  setsid nohup bash scripts/properties/resume_chain.sh &
set -u
cd "$(dirname "$0")/../.."
P=/path/to/user/anaconda3/envs/matgenbench-py310/bin/python
LOGS=data/props_work/_logs
mkdir -p "$LOGS"
rm -f "$LOGS/chain-complete.marker"

echo "chain started $(date)" >> "$LOGS/chain.log"
$P scripts/properties/run_all.py --phase main --nproc 26 >> "$LOGS/driver-main.log" 2>&1 \
  && $P scripts/properties/run_all.py --sources jarvis-dft oqmd --nproc 26 >> "$LOGS/driver-extra.log" 2>&1 \
  && $P scripts/properties/run_all.py --phase huge --nproc 26 >> "$LOGS/driver-huge.log" 2>&1 \
  && $P scripts/properties/run_all.py --phase backfill >> "$LOGS/driver-backfill.log" 2>&1 \
  && $P scripts/properties/curves.py rruff >> "$LOGS/curves-load.log" 2>&1
STATUS=$?
echo "chain finished $(date) exit=$STATUS" >> "$LOGS/chain.log"
echo "$STATUS" > "$LOGS/chain-complete.marker"
