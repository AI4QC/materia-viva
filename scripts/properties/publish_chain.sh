#!/usr/bin/env bash
# Final chain: wait for core-mof, refresh the cached counts, build the frontend
# development slice, then stage everything for Hugging Face.
#   setsid nohup bash scripts/properties/publish_chain.sh &
#
# Stops before the upload itself -- pushing ~47 GB to a remote is not something
# a background script should start unattended.
set -u
cd "$(dirname "$0")/../.."
P="${MATERIAVIVA_PYTHON:-python3}"
LOGS=data/props_work/_logs
OUT=/tmp/local-workspace
mkdir -p "$LOGS" "$OUT"
rm -f "$LOGS/publish-complete.marker"
echo "publish chain started $(date)" >> "$LOGS/chain.log"

while pgrep -f "core_mof_chain.sh|hmof_chain.sh|fix_framework_hash_refs.sh|repair_and_verify.sh|finalize_all.sh" > /dev/null; do
  sleep 60
done
echo "publish: index quiet $(date)" >> "$LOGS/chain.log"

# summarize also refreshes metadata.property_row_count / curve_count, which is
# what /api/stats reads for the landing-page figures.
"$P" scripts/properties/summarize.py > "$OUT/summary-complete.md" 2>>"$LOGS/publish.log"

# Coverage-complete slice: --limit is only the top-up target, the set cover is
# never truncated (see scripts/export_slice.py).
"$P" scripts/export_slice.py --out data/slice --limit 1000 >> "$LOGS/slice-build.log" 2>&1 \
  || echo "publish: slice build failed" >> "$LOGS/chain.log"

# Prove the slice actually serves before anyone downloads it.
"$P" - <<'PYEOF' >> "$LOGS/slice-build.log" 2>&1
import sys
sys.path.insert(0, 'backend')
from pathlib import Path
from materials_api.repository import MaterialRepository
root = Path('data/slice')
repo = MaterialRepository(root / 'materials.sqlite', root / 'structures.blob')
stats = repo.stats()
print('slice stats:', {k: stats.get(k) for k in
                       ('total', 'datasets', 'property_rows', 'curve_count')})
PYEOF

"$P" scripts/properties/verify_complete.py --json "$OUT/verify-complete.json" \
    > "$OUT/verify-complete.txt" 2>&1
echo "$?" > "$LOGS/verify-complete.marker"

"$P" scripts/prepare_hf_upload.py >> "$LOGS/publish.log" 2>&1 \
  || echo "publish: staging failed" >> "$LOGS/chain.log"

echo "0" > "$LOGS/publish-complete.marker"
echo "publish chain finished $(date)" >> "$LOGS/chain.log"
