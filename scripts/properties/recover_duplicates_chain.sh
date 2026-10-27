#!/usr/bin/env bash
# Recover properties dropped as intra-source fingerprint duplicates, with the
# method strings that make the recovered rows meaningful:
#   * jarvis-qetb  — volume per atom in the method (it is an EOS fitting set,
#                    so one crystal carries dozens of different energies)
#   * aflow        — the AFLOW catalog in the method (ICSD_WEB differs from the
#                    LIB catalogs by up to 3.7 eV/atom on the same crystal)
# jarvis-qetb is re-loaded from scratch (its flat-method rows were rolled back);
# aflow is re-staged and repaired in place.
#   setsid nohup bash scripts/properties/recover_duplicates_chain.sh &
set -u
cd "$(dirname "$0")/../.."
P="${MATERIAVIVA_PYTHON:-python3}"
LOGS=data/props_work/_logs
mkdir -p "$LOGS"
rm -f "$LOGS/recover-complete.marker"
echo "duplicate recovery v2 started $(date)" >> "$LOGS/chain.log"

# jarvis-qetb: full clean re-load under the volume-tagged method
rm -f data/props_work/jarvis-qetb/matched.tsv.gz \
      data/props_work/jarvis-qetb/new_structs.jsonl.gz \
      data/props_work/jarvis-qetb/alias.tsv.gz
"$P" scripts/properties/run_all.py --sources jarvis-qetb --nproc 24 \
    >> "$LOGS/recover-jarvis-qetb.log" 2>&1

# aflow: re-stage, then repair the orphaned duplicates in place
"$P" scripts/properties/pipeline.py aflow --stage adapt --nproc 24 \
    >> "$LOGS/recover-aflow.log" 2>&1 \
  && "$P" scripts/properties/pipeline.py aflow --stage hash --nproc 24 \
    >> "$LOGS/recover-aflow.log" 2>&1 \
  && "$P" scripts/properties/repair_duplicate_props.py aflow \
    >> "$LOGS/recover-aflow.log" 2>&1

"$P" scripts/properties/run_all.py --phase backfill >> "$LOGS/recover-backfill.log" 2>&1
echo "duplicate recovery v2 finished $(date)" >> "$LOGS/chain.log"
echo "0" > "$LOGS/recover-complete.marker"
