#!/usr/bin/env bash
# Wait for finalize_all.sh, then work the repair queue that the completeness
# audit turned up, then audit again. Self-chaining: it must outlive the agent
# session that launched it.
#   setsid nohup bash scripts/properties/repair_and_verify.sh &
#
# Repairs here are the ones whose inputs already exist. Sources needing a full
# re-adapt/hash (hmof, deem-zeolites, pcod) are driven separately once their
# extractors land -- see docs/property-integration.md.
set -u
cd "$(dirname "$0")/../.."
P=/path/to/user/anaconda3/envs/matgenbench-py310/bin/python
LOGS=data/props_work/_logs
OUT=/tmp/local-workspace
mkdir -p "$LOGS" "$OUT"
rm -f "$LOGS/repair-complete.marker" "$LOGS/verify-complete.marker"
echo "repair+verify supervisor started $(date)" >> "$LOGS/chain.log"

while true; do
  [ -f "$LOGS/finalize-complete.marker" ] && break
  if ! pgrep -f "finalize_all.sh" > /dev/null; then
    echo "repair: finalize gone without marker $(date)" >> "$LOGS/chain.log"
    break
  fi
  sleep 120
done
echo "repair: finalize clear, starting repairs $(date)" >> "$LOGS/chain.log"

clear_marker () {
  $P - "$1" <<'PYEOF'
import json, sys
sys.path.insert(0, '.'); sys.path.insert(0, 'backend')
from scripts.properties.load import connect
source = sys.argv[1]
db = connect()
row = db.execute("SELECT value FROM metadata WHERE key='loaded_property_sources'").fetchone()
loaded = json.loads(row[0]) if row else {}
loaded.pop(source, None)
db.execute("INSERT OR REPLACE INTO metadata (key, value) VALUES ('loaded_property_sources', ?)",
           (json.dumps(loaded, sort_keys=True),))
db.commit(); db.close()
print(f"{source}: load marker cleared")
PYEOF
}

# --- 1. Sources whose 2026-08-19 adapt discovered authoritative id links that
#        their load never consumed: they ran before load.py learned to read
#        id_matches.tsv.gz. No re-adapt is needed -- the fresh id_matches.tsv.gz
#        is already on disk, and load.py now folds it in. Measured stranded
#        pairs at 2026-08-19 11:15:
#          cod 213,500 | cmr-static 98,021 | materials-cloud-archive-static 34
#        (3dsc/spse/webmineral/amdb/obelix were re-loaded after the fix and
#        already consumed theirs -- their id_links_refreshed counters prove it.)
for s in cod cmr-static materials-cloud-archive-static; do
  echo "=== $s re-load $(date) ===" >> "$LOGS/repair-$s.log"
  clear_marker "$s" >> "$LOGS/repair-$s.log" 2>&1
  $P scripts/properties/load.py load "$s" >> "$LOGS/repair-$s.log" 2>&1 \
    || echo "repair: $s re-load failed" >> "$LOGS/chain.log"
done

# --- 2. aflow: 1,120 exact duplicate property rows from 164 records ingested
#        twice. material_source_refs deduped them via its primary key;
#        material_properties has no uniqueness constraint, so both copies
#        survived. Keep one row per full key.
$P scripts/properties/dedupe_exact_props.py --source aflow \
    >> "$LOGS/repair-aflow-dedupe.log" 2>&1 \
  || echo "repair: aflow dedupe failed" >> "$LOGS/chain.log"

echo "0" > "$LOGS/repair-complete.marker"
echo "repair: repairs done, auditing $(date)" >> "$LOGS/chain.log"

# --- 3. full audit incl. the per-source field-coverage scan, plus a fresh
#        summary table for the docs.
$P scripts/properties/verify_complete.py --json "$OUT/verify-complete.json" \
    > "$OUT/verify-complete.txt" 2>&1
echo "$?" > "$LOGS/verify-complete.marker"
$P scripts/properties/summarize.py > "$OUT/summary-complete.md" 2>/dev/null

echo "repair+verify supervisor finished $(date)" >> "$LOGS/chain.log"
