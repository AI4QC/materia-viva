#!/usr/bin/env bash
# Land the NOMAD 2026-09-05 export: relaxed structures plus catalog scalars.
#   setsid nohup bash scripts/properties/nomad_chain.sh &
#
# Stages, in order, each resumable on its own artifacts under data/props_work/nomad/:
#   0  snapshot the index so a bad load can be rolled back
#   1  catalog -> catalog_scalars.sqlite   (19.4M entries -> one row per
#                                           material/property/level of theory)
#   2  adapt   -> staging_props.tsv.gz + staging_structs.jsonl.gz
#   3  hash    -> BAWL fingerprints, the long pole
#   4  match   -> matched.tsv.gz + new_structs.jsonl.gz
#   5  load    -> index, then scalar backfill and the completeness audit
#
# NOMAD aggregates uploads that other sources already contributed under their
# own provenance, so nearly everything here is expected to fingerprint-match an
# existing pool material rather than be admitted. That is the point.
set -u
cd "$(dirname "$0")/../.."
P=/path/to/user/anaconda3/envs/matgenbench-py310/bin/python
WORK=data/props_work/nomad
LOGS=data/props_work/_logs
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$WORK" "$LOGS"
LOG="$LOGS/nomad-chain.log"
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "=== nomad chain start $STAMP ==="

# --- 0. rollback point -------------------------------------------------------
# The blobs are append-only, so their byte counts are enough to truncate back;
# the sqlite needs a real copy.
if [ ! -f data/index/pre-nomad-restore-info.json ]; then
  say "snapshotting index before the load"
  $P - <<'PYEOF' >> "$LOG" 2>&1
import json, pathlib, shutil
idx = pathlib.Path("data/index")
info = {name: (idx / name).stat().st_size
        for name in ("structures.blob", "curves.blob")}
info["note"] = "truncate the blobs to these sizes and restore the .bak to undo the NOMAD load"
shutil.copy2(idx / "materials.sqlite", idx / "materials.sqlite.pre-nomad.bak")
(idx / "pre-nomad-restore-info.json").write_text(json.dumps(info, indent=2))
print("snapshot written:", info)
PYEOF
  [ $? -eq 0 ] || { say "snapshot FAILED"; exit 1; }
else
  say "snapshot already present, skipping"
fi

# --- 1. catalog scalars ------------------------------------------------------
if [ ! -f "$WORK/catalog_scalars.done" ]; then
  say "stage 1/5 catalog scalars"
  $P scripts/properties/nomad_catalog_scalars.py \
      --out "$WORK/catalog_scalars.sqlite" >> "$LOG" 2>&1 \
    && touch "$WORK/catalog_scalars.done" \
    || { say "catalog scalars FAILED"; exit 1; }
else
  say "stage 1/5 catalog scalars already done"
fi

# --- 2. adapt ----------------------------------------------------------------
if [ ! -f "$WORK/adapt.done" ]; then
  say "stage 2/5 adapt"
  $P scripts/properties/pipeline.py nomad --stage adapt >> "$LOG" 2>&1 \
    && touch "$WORK/adapt.done" || { say "adapt FAILED"; exit 1; }
else
  say "stage 2/5 adapt already done"
fi

# --- 3. hash -----------------------------------------------------------------
if [ ! -f "$WORK/hash.done" ]; then
  say "stage 3/5 hash (the long pole)"
  $P scripts/properties/pipeline.py nomad --stage hash --nproc 28 >> "$LOG" 2>&1 \
    && touch "$WORK/hash.done" || { say "hash FAILED"; exit 1; }
else
  say "stage 3/5 hash already done"
fi

# --- 4. match ----------------------------------------------------------------
if [ ! -f "$WORK/match.done" ]; then
  say "stage 4/5 match"
  $P scripts/properties/pipeline.py nomad --stage match >> "$LOG" 2>&1 \
    && touch "$WORK/match.done" || { say "match FAILED"; exit 1; }
else
  say "stage 4/5 match already done"
fi

# --- 5. load, backfill, audit ------------------------------------------------
say "stage 5/5 load"
$P scripts/properties/load.py load nomad >> "$LOG" 2>&1 \
  || { say "load FAILED"; exit 1; }
say "scalar backfill"
$P scripts/properties/load.py backfill >> "$LOG" 2>&1 || say "backfill returned nonzero"
say "completeness audit"
$P scripts/properties/verify_complete.py >> "$LOG" 2>&1 || say "audit reported problems"
say "summarize"
$P scripts/properties/summarize.py >> "$LOG" 2>&1 || say "summarize returned nonzero"

say "=== nomad chain complete ==="
touch "$LOGS/nomad-complete.marker"
