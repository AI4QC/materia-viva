#!/usr/bin/env bash
# Supervisor: waits for the in-flight batch-2 chain, then runs batch 3 on its
# own, so no step depends on anyone watching. Detached:
#   setsid nohup bash scripts/properties/supervise_all.sh &
set -u
cd "$(dirname "$0")/../.."
LOGS=data/props_work/_logs
mkdir -p "$LOGS"
rm -f "$LOGS/all-complete.marker"
echo "supervisor started $(date)" >> "$LOGS/chain.log"

# 1. wait for batch 2 (COD + carolina + aflow-ael + backfill + curves)
while [ ! -f "$LOGS/chain2-complete.marker" ]; do
  if ! pgrep -f resume_chain2.sh > /dev/null; then
    echo "supervisor: chain2 process gone without marker $(date)" >> "$LOGS/chain.log"
    echo "chain2-died" > "$LOGS/all-complete.marker"
    exit 1
  fi
  sleep 60
done
echo "supervisor: chain2 done, starting chain3 $(date)" >> "$LOGS/chain.log"

# 2. batch 3 (HF supplement sources + phonon payload)
bash scripts/properties/resume_chain3.sh
STATUS=$?

echo "supervisor: all done $(date) exit=$STATUS" >> "$LOGS/chain.log"
echo "$STATUS" > "$LOGS/all-complete.marker"
