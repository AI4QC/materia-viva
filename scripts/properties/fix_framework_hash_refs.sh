#!/usr/bin/env bash
# Undo the fingerprint-collapse contamination for the enumerated-framework
# sources, then re-land their properties and curves cleanly.
#   setsid nohup bash scripts/properties/fix_framework_hash_refs.sh &
#
# BAWL cannot tell idealized silica / aluminophosphate nets apart, so the
# `hash` refs for deem-zeolites and pcod claim identities that are not real:
# 190,655 Deem refs land on 1,552 materials, three of which had collected
# 27,007 XRD patterns and 593,036 property rows apiece from frameworks that are
# not them. load.FINGERPRINT_UNRELIABLE now stops the loader re-creating them
# and the Deem curve source reads only `origin` refs, so this script only has
# to clear what the earlier runs already wrote.
set -u
cd "$(dirname "$0")/../.."
P=/home/zhilong/anaconda3/envs/matgenbench-py310/bin/python
LOGS=data/props_work/_logs
OUT=/tmp/claude-1000/-home-zhilong-workspace-matdata
mkdir -p "$LOGS" "$OUT"
rm -f "$LOGS/frameworkfix-complete.marker"
echo "framework hash-ref fix started $(date)" >> "$LOGS/chain.log"

while pgrep -f "load_new_extractors.sh|repair_and_verify.sh|finalize_all.sh" > /dev/null; do
  sleep 30
done

$P - <<'PYEOF' >> "$LOGS/frameworkfix.log" 2>&1
import sys
sys.path.insert(0, '.'); sys.path.insert(0, 'backend')
from scripts.properties.load import connect, FINGERPRINT_UNRELIABLE

db = connect()
db.execute("PRAGMA busy_timeout = 600000")
for key in sorted(FINGERPRINT_UNRELIABLE):
    row = db.execute("SELECT id FROM source_defs WHERE key = ?", (key,)).fetchone()
    if row is None:
        print(f"{key}: not in source_defs, skipped")
        continue
    sid = row[0]
    before = db.execute(
        "SELECT COUNT(*) FROM material_source_refs WHERE source_id = ? AND match_via = 'hash'",
        (sid,),
    ).fetchone()[0]
    db.execute(
        "DELETE FROM material_source_refs WHERE source_id = ? AND match_via = 'hash'",
        (sid,),
    )
    db.commit()
    kept = db.execute(
        "SELECT COUNT(*) FROM material_source_refs WHERE source_id = ?", (sid,)
    ).fetchone()[0]
    print(f"{key}: deleted {before:,} hash refs, {kept:,} origin refs kept", flush=True)
db.close()
PYEOF

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

for s in pcod deem-zeolites; do
  echo "=== $s clean re-load $(date) ===" >> "$LOGS/frameworkfix-$s.log"
  clear_marker "$s" >> "$LOGS/frameworkfix-$s.log" 2>&1
  $P scripts/properties/load.py load "$s" >> "$LOGS/frameworkfix-$s.log" 2>&1 \
    || echo "frameworkfix: $s load failed" >> "$LOGS/chain.log"
done

# Replaces the source's curves wholesale, so the 326,663 contaminated rows go.
$P scripts/properties/curves.py deem-zeolites >> "$LOGS/frameworkfix-deem-curves.log" 2>&1 \
  || echo "frameworkfix: deem curves failed" >> "$LOGS/chain.log"

echo "0" > "$LOGS/frameworkfix-complete.marker"

$P scripts/properties/verify_complete.py --json "$OUT/verify-complete.json" \
    > "$OUT/verify-complete.txt" 2>&1
echo "$?" > "$LOGS/verify-complete.marker"
$P scripts/properties/summarize.py > "$OUT/summary-complete.md" 2>/dev/null

echo "framework hash-ref fix finished $(date)" >> "$LOGS/chain.log"
