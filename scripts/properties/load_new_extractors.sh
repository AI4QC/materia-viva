#!/usr/bin/env bash
# Land the two newly written extractors, then re-audit.
#   setsid nohup bash scripts/properties/load_new_extractors.sh &
#
# Neither source needs hashing or matching: their structures were admitted long
# ago (deem-zeolites through deem_zeolite_admit.py's composite key, pcod through
# its original run), so matched.tsv.gz plus the links already in
# material_source_refs reach every record. Only the property side is new.
#
# Deliberately NOT re-running --stage match for either: both corpora are
# enumerated predicted frameworks, where a BAWL collision is usually a FALSE
# duplicate -- two genuinely different frameworks that happen to fingerprint
# alike. Aliasing them would staple one framework's moduli onto another.
set -u
cd "$(dirname "$0")/../.."
P="${MATERIAVIVA_PYTHON:-python3}"
LOGS=data/props_work/_logs
OUT=/tmp/local-workspace
mkdir -p "$LOGS" "$OUT"
rm -f "$LOGS/extractors-complete.marker"
echo "extractor load started $(date)" >> "$LOGS/chain.log"

# Never run concurrently with another writer to the index.
while pgrep -f "repair_and_verify.sh|finalize_all.sh" > /dev/null; do sleep 60; done

clear_marker () {
  "$P" - "$1" <<'PYEOF'
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

for s in pcod deem-zeolites; do
  echo "=== $s load $(date) ===" >> "$LOGS/extractor-$s.log"
  clear_marker "$s" >> "$LOGS/extractor-$s.log" 2>&1
  "$P" scripts/properties/load.py load "$s" >> "$LOGS/extractor-$s.log" 2>&1 \
    || echo "extractor: $s load failed" >> "$LOGS/chain.log"
done

# Simulated XRD stick patterns, 1:1 with the Deem CIFs.
"$P" scripts/properties/curves.py deem-zeolites >> "$LOGS/extractor-deem-curves.log" 2>&1 \
  || echo "extractor: deem curves failed" >> "$LOGS/chain.log"

echo "0" > "$LOGS/extractors-complete.marker"

"$P" scripts/properties/verify_complete.py --json "$OUT/verify-complete.json" \
    > "$OUT/verify-complete.txt" 2>&1
echo "$?" > "$LOGS/verify-complete.marker"
"$P" scripts/properties/summarize.py > "$OUT/summary-complete.md" 2>/dev/null

echo "extractor load finished $(date)" >> "$LOGS/chain.log"
