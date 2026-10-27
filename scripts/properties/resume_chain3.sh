#!/usr/bin/env bash
# Batch 3: the HF local-dataset supplements (7 integrable sources) plus the
# recomputed PhononDB phonon payload.
# Run detached:  setsid nohup bash scripts/properties/resume_chain3.sh &
set -u
cd "$(dirname "$0")/../.."
P="${MATERIAVIVA_PYTHON:-python3}"
LOGS=data/props_work/_logs
mkdir -p "$LOGS"
rm -f "$LOGS/chain3-complete.marker"
echo "chain3 started $(date)" >> "$LOGS/chain.log"

# properties-only + small structure sources first, then the big ones
SMALL="amdb webmineral iza-zeolite openmx-2d-ab2"
BIG="phonondb pcod"

# wipe dry-run staging so the full adapt runs
for s in $SMALL $BIG; do
  rm -f "data/props_work/$s/staging_props.tsv.gz" \
        "data/props_work/$s/id_matches.tsv.gz" \
        "data/props_work/$s/staging_structs.jsonl.gz" \
        "data/props_work/$s/hashes.tsv.gz" \
        "data/props_work/$s/matched.tsv.gz" \
        "data/props_work/$s/new_structs.jsonl.gz" \
        "data/props_work/$s/report.json"
done

"$P" scripts/properties/run_all.py --sources $SMALL --nproc 24 >> "$LOGS/driver-batch3.log" 2>&1 \
  && "$P" scripts/properties/run_all.py --sources $BIG --nproc 24 >> "$LOGS/driver-batch3.log" 2>&1
STATUS=$?

# phonon scalars recomputed with phonopy (needs phonondb loaded first)
if [ -f data/props_work/phonondb/phonons.jsonl.gz ]; then
  "$P" scripts/properties/phonondb_attach.py >> "$LOGS/phonondb-attach.log" 2>&1 \
    || echo "phonondb attach failed" >> "$LOGS/chain.log"
fi

"$P" scripts/properties/run_all.py --phase backfill >> "$LOGS/driver-batch3.log" 2>&1

# curve stores that gained data in this batch
for s in phonondb; do
  "$P" scripts/properties/curves.py "$s" >> "$LOGS/curves-load.log" 2>&1 \
    || echo "curves $s failed" >> "$LOGS/chain.log"
done

"$P" scripts/properties/summarize.py \
  > /tmp/local-workspace/summary-batch3.md 2>/dev/null

echo "chain3 finished $(date) exit=$STATUS" >> "$LOGS/chain.log"
echo "$STATUS" > "$LOGS/chain3-complete.marker"
