#!/bin/sh
# Launch the Atomly harvester detached from any terminal (survives Cursor restarts).
# Idempotent: a daily cron calls this; it exits quietly when a harvester is alive.
# Usage: sh scripts/datasets/atomly_run.sh [extra atomly.py args...]
if pgrep -f "atomly.py --phase all" > /dev/null 2>&1; then
    echo "harvester already running; nothing to do"
    exit 0
fi
cd "$(dirname "$0")/../.." || exit 1
LOG_DIR="${MV_ATOMLY_LOG_DIR:-data/raw/acquired/atomly/_logs}"
mkdir -p "$LOG_DIR"
TS=$(date +%Y%m%d-%H%M%S)
PYTHONPATH=. nohup python3 scripts/datasets/atomly.py --phase all --auth session --rps 1.8 "$@" \
    > "$LOG_DIR/harvest-$TS.log" 2>&1 &
echo "started pid $! log $LOG_DIR/harvest-$TS.log"
