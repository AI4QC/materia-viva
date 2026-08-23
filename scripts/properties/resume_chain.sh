#!/usr/bin/env bash
# Resume the full property-ingestion chain; every stage is idempotent/resumable.
# Run detached:  setsid nohup bash scripts/properties/resume_chain.sh &
set -u
cd "$(dirname "$0")/../.."
P="${MV_PYTHON:-$(command -v python3)}"
#: unset -> each script picks a worker count from this machine's cores
NPROC="${MV_NPROC:+--nproc $MV_NPROC}"
LOGS=data/props_work/_logs
mkdir -p "$LOGS"
rm -f "$LOGS/chain-complete.marker"

echo "chain started $(date)" >> "$LOGS/chain.log"
$P scripts/properties/run_all.py --phase main $NPROC >> "$LOGS/driver-main.log" 2>&1 \
  && $P scripts/properties/run_all.py --sources jarvis-dft oqmd $NPROC >> "$LOGS/driver-extra.log" 2>&1 \
  && $P scripts/properties/run_all.py --phase huge $NPROC >> "$LOGS/driver-huge.log" 2>&1 \
  && $P scripts/properties/run_all.py --phase backfill >> "$LOGS/driver-backfill.log" 2>&1 \
  && $P scripts/properties/curves.py rruff >> "$LOGS/curves-load.log" 2>&1
STATUS=$?
echo "chain finished $(date) exit=$STATUS" >> "$LOGS/chain.log"
echo "$STATUS" > "$LOGS/chain-complete.marker"
