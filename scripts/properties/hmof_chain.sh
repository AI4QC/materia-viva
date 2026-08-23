#!/usr/bin/env bash
# Land hMOF properly: full adapt (the staging on disk is a 300-record test
# stub), re-hash, then composite-key admission.
#   setsid nohup bash scripts/properties/hmof_chain.sh &
#
# Deliberately NOT `--stage match` and NOT load.py, per the order of operations
# in hmof_composite_admit.py: every hMOF fingerprint is already in hash_map, so
# a match would resolve all 137,652 records onto the 88,927 existing materials
# and the loader would smear 46,891 distinct frameworks' porosities and CO2
# isotherms across them. The composite-key admitter does the work of both
# stages itself, reading hashes/staging_structs/staging_props directly.
#
# --purge-ambiguous-hashes also clears fingerprints that serve more than one
# material out of the match map, so no later source can resolve through them.
# That is the same contamination class already fixed for deem-zeolites and pcod
# (see load.FINGERPRINT_UNRELIABLE).
set -u
cd "$(dirname "$0")/../.."
P="${MV_PYTHON:-$(command -v python3)}"
LOGS=data/props_work/_logs
OUT="${MV_OUT:-data/props_work/_out}"
mkdir -p "$LOGS" "$OUT"
rm -f "$LOGS/hmof-complete.marker"
echo "hmof chain started $(date)" >> "$LOGS/chain.log"

while pgrep -f "fix_framework_hash_refs.sh|load_new_extractors.sh|repair_and_verify.sh|finalize_all.sh" > /dev/null; do
  sleep 30
done

$P scripts/properties/pipeline.py hmof --stage adapt --nproc 20 \
    >> "$LOGS/hmof-chain.log" 2>&1 || {
  echo "hmof: adapt failed" >> "$LOGS/chain.log"; exit 1; }

$P scripts/properties/pipeline.py hmof --stage hash --nproc 20 \
    >> "$LOGS/hmof-chain.log" 2>&1 || {
  echo "hmof: hash failed" >> "$LOGS/chain.log"; exit 1; }

# Dry run first: it prints the full classification without writing, so the
# apply below is never the first time anyone sees these counters.
$P scripts/properties/hmof_composite_admit.py \
    >> "$LOGS/hmof-admit-dryrun.log" 2>&1 \
  || echo "hmof: dry run failed" >> "$LOGS/chain.log"

$P scripts/properties/hmof_composite_admit.py --apply --purge-ambiguous-hashes \
    >> "$LOGS/hmof-admit.log" 2>&1 \
  || echo "hmof: composite admit failed" >> "$LOGS/chain.log"

echo "0" > "$LOGS/hmof-complete.marker"

$P scripts/properties/verify_complete.py --json "$OUT/verify-complete.json" \
    > "$OUT/verify-complete.txt" 2>&1
echo "$?" > "$LOGS/verify-complete.marker"
$P scripts/properties/summarize.py > "$OUT/summary-complete.md" 2>/dev/null

echo "hmof chain finished $(date)" >> "$LOGS/chain.log"
