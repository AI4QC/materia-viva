#!/usr/bin/env bash
# Batch 2: A/B/C integrations approved 2026-08-18.
# Run detached:  setsid nohup bash scripts/properties/resume_chain2.sh &
set -u
cd "$(dirname "$0")/../.."
P=/home/zhilong/anaconda3/envs/matgenbench-py310/bin/python
LOGS=data/props_work/_logs
mkdir -p "$LOGS"
rm -f "$LOGS/chain2-complete.marker"
echo "chain2 started $(date)" >> "$LOGS/chain.log"

RERUN="cmr-static jarvis-specialized-structures superband"
NEW_SMALL="curated-cof core-mof mc3d qmof icsd csllm-negatives"
NEW_BIG="jarvis-qetb cod"

# 0a. new sources: wipe dry-run staging entirely so the full adapt runs
for s in $NEW_SMALL $NEW_BIG; do
  rm -f "data/props_work/$s/staging_props.tsv.gz" \
        "data/props_work/$s/id_matches.tsv.gz" \
        "data/props_work/$s/staging_structs.jsonl.gz" \
        "data/props_work/$s/hashes.tsv.gz" \
        "data/props_work/$s/matched.tsv.gz" \
        "data/props_work/$s/new_structs.jsonl.gz" \
        "data/props_work/$s/report.json"
done
# 0b. re-run sources: their extended FULL adapt staging is already on disk;
# drop only the stale downstream artifacts so hash/match recompute
for s in $RERUN; do
  rm -f "data/props_work/$s/hashes.tsv.gz" \
        "data/props_work/$s/matched.tsv.gz" \
        "data/props_work/$s/new_structs.jsonl.gz" \
        "data/props_work/$s/load_report.json"
done
$P - <<'PYEOF'
import json, sys
sys.path.insert(0, '.'); sys.path.insert(0, 'backend')
from scripts.properties.load import connect
db = connect()
row = db.execute(
    "SELECT value FROM metadata WHERE key='loaded_property_sources'"
).fetchone()
loaded = json.loads(row[0]) if row else {}
for key in ('cmr-static', 'jarvis-specialized-structures', 'superband'):
    loaded.pop(key, None)
db.execute(
    "INSERT OR REPLACE INTO metadata (key, value) VALUES "
    "('loaded_property_sources', ?)", (json.dumps(loaded, sort_keys=True),))
db.commit(); db.close()
print('re-run markers cleared')
PYEOF

run_sources () {
  $P scripts/properties/run_all.py --sources $1 --nproc 26 >> "$LOGS/driver-batch2.log" 2>&1
}

run_sources "$RERUN" \
  && run_sources "$NEW_SMALL" \
  && run_sources "$NEW_BIG" \
  && $P scripts/properties/carolina_refs.py >> "$LOGS/carolina-refs.log" 2>&1
STATUS=$?

if [ -f scripts/properties/aflow_ael_attach.py ]; then
  $P scripts/properties/aflow_ael_attach.py >> "$LOGS/aflow-ael.log" 2>&1 \
    || echo "aflow ael attach failed" >> "$LOGS/chain.log"
fi

$P scripts/properties/run_all.py --phase backfill >> "$LOGS/driver-batch2.log" 2>&1

for s in rruff materiae phonix superband; do
  $P scripts/properties/curves.py "$s" >> "$LOGS/curves-load.log" 2>&1 \
    || echo "curves $s failed" >> "$LOGS/chain.log"
done

$P scripts/properties/summarize.py \
  > /tmp/claude-1000/-home-zhilong-workspace-matdata/summary-batch2.md 2>/dev/null

echo "chain2 finished $(date) exit=$STATUS" >> "$LOGS/chain.log"
echo "$STATUS" > "$LOGS/chain2-complete.marker"
