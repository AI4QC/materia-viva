#!/usr/bin/env bash
# Land CoRE MOF's newly acquired Zeo++ porosity table.
#   setsid nohup bash scripts/properties/core_mof_chain.sh &
#
# The adapt is already done (19,081 records / 152,648 property rows, full run).
# What is missing is hash -> match -> load: report.json's hash and match blocks
# still describe the 2026-08-17 structure-only run, and matched.tsv.gz with it,
# so a load alone would attach nothing new for records matched by fingerprint.
#
# Unlike deem-zeolites/pcod/hmof, CoRE MOF is NOT an enumerated library -- these
# are experimentally reported MOFs with distinct CSD refcodes, so the BAWL
# fingerprint is trustworthy here and the normal match stage applies.
set -u
cd "$(dirname "$0")/../.."
P=/home/zhilong/anaconda3/envs/matgenbench-py310/bin/python
LOGS=data/props_work/_logs
OUT=/tmp/claude-1000/-home-zhilong-workspace-matdata
mkdir -p "$LOGS" "$OUT"
rm -f "$LOGS/coremof-complete.marker"
echo "core-mof chain started $(date)" >> "$LOGS/chain.log"

# hmof's hash stage saturates 20 cores; wait it out rather than fight for CPU.
while pgrep -f "hmof_chain.sh|fix_framework_hash_refs.sh|load_new_extractors.sh|repair_and_verify.sh|finalize_all.sh" > /dev/null; do
  sleep 60
done

$P scripts/properties/pipeline.py core-mof --stage hash --nproc 20 \
    >> "$LOGS/coremof-chain.log" 2>&1 || {
  echo "core-mof: hash failed" >> "$LOGS/chain.log"; exit 1; }

$P scripts/properties/pipeline.py core-mof --stage match \
    >> "$LOGS/coremof-chain.log" 2>&1 || {
  echo "core-mof: match failed" >> "$LOGS/chain.log"; exit 1; }

$P - core-mof <<'PYEOF' >> "$LOGS/coremof-chain.log" 2>&1
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

$P scripts/properties/load.py load core-mof >> "$LOGS/coremof-chain.log" 2>&1 \
  || echo "core-mof: load failed" >> "$LOGS/chain.log"

echo "0" > "$LOGS/coremof-complete.marker"

$P scripts/properties/verify_complete.py --json "$OUT/verify-complete.json" \
    > "$OUT/verify-complete.txt" 2>&1
echo "$?" > "$LOGS/verify-complete.marker"
$P scripts/properties/summarize.py > "$OUT/summary-complete.md" 2>/dev/null

echo "core-mof chain finished $(date)" >> "$LOGS/chain.log"
