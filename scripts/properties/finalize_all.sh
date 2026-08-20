#!/usr/bin/env bash
# Final pass: re-stage and re-load every source whose adapter gained newly
# mapped fields, run the ICSD fingerprint bridge and its cascade, admit the
# fingerprint-colliding hMOFs under a composite key, then backfill and
# summarise. Waits for the duplicate-recovery chain to finish first.
#   setsid nohup bash scripts/properties/finalize_all.sh &
set -u
cd "$(dirname "$0")/../.."
P=/home/zhilong/anaconda3/envs/matgenbench-py310/bin/python
LOGS=data/props_work/_logs
mkdir -p "$LOGS"
rm -f "$LOGS/finalize-complete.marker"
echo "finalize started $(date)" >> "$LOGS/chain.log"

# 0. wait for the in-flight duplicate recovery (aflow / jarvis-qetb)
while pgrep -f recover_duplicates_chain.sh > /dev/null; do sleep 60; done
echo "finalize: recovery chain clear $(date)" >> "$LOGS/chain.log"

# Sources whose adapters gained fields. They need adapt (new staged props) and
# load (which clears the source's old rows and re-inserts). matched.tsv.gz
# survives for all of them and load now also seeds from existing refs, so the
# expensive hash/match stages are skipped entirely.
REMAP="gnome matbench-discovery materials-project mof-carbon-capture mofx-db qmof \
fair-mofs elementa jarvis-dft materiae jarvis-specialized-structures spse phonix cod \
cmr-static novomag materials-cloud-archive-static 3dsc bidb sacada aflow-prototypes \
ec-mof webmineral hex-high-pressure open-framework-aluminophosphate tcod rruff snumat \
obelix mc2d"

reload_source () {
  local s="$1"
  [ -d "data/props_work/$s" ] || return 0
  echo "=== $s $(date) ===" >> "$LOGS/finalize-$s.log"
  $P scripts/properties/pipeline.py "$s" --stage adapt --nproc 20 \
      >> "$LOGS/finalize-$s.log" 2>&1 || return 0
  # allow the re-load: clear the marker so load.py replaces this source's rows
  $P - "$s" <<'PYEOF' >> "$LOGS/finalize-$s.log" 2>&1
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
  $P scripts/properties/load.py load "$s" >> "$LOGS/finalize-$s.log" 2>&1 \
    || echo "load failed: $s" >> "$LOGS/chain.log"
}

for s in $REMAP; do reload_source "$s"; done

# 1. ICSD fingerprint bridge: hash the local ICSD CIFs, match them (properties_only
#    means nothing is ever admitted), register the id->material pairs, then re-run
#    the sources that key on ICSD ids so they pick up the new links.
if [ -f scripts/properties/icsd_bridge.py ]; then
  $P scripts/properties/pipeline.py icsd --stage adapt --nproc 20 >> "$LOGS/finalize-icsd.log" 2>&1
  $P scripts/properties/pipeline.py icsd --stage hash --nproc 20 >> "$LOGS/finalize-icsd.log" 2>&1
  $P scripts/properties/pipeline.py icsd --stage match >> "$LOGS/finalize-icsd.log" 2>&1
  $P scripts/properties/icsd_bridge.py >> "$LOGS/finalize-icsd.log" 2>&1
  for s in icsd 3dsc spse webmineral amdb obelix; do reload_source "$s"; done
fi

# 2. hMOF fingerprint collisions: composite-key admission (never aliasing —
#    these are distinct frameworks whose bonding graphs collide)
if [ -f scripts/properties/hmof_composite_admit.py ]; then
  $P scripts/properties/hmof_composite_admit.py >> "$LOGS/finalize-hmof.log" 2>&1 \
    || echo "hmof composite admit failed" >> "$LOGS/chain.log"
fi

# 2b. Materials Project spectra: 817k curves (DOS, band structures, XAS,
#     phonon DOS, optical absorption) from the 2026-08-19 acquisition
if [ -f scripts/properties/curve_sources/materials_project.py ]; then
  $P scripts/properties/curves.py materials-project >> "$LOGS/curves-load.log" 2>&1 \
    || echo "mp curves failed" >> "$LOGS/chain.log"
fi

# 3. whole-pool backfill + fresh summary
$P scripts/properties/run_all.py --phase backfill >> "$LOGS/finalize-backfill.log" 2>&1
$P scripts/properties/summarize.py > /tmp/claude-1000/-home-zhilong-workspace-matdata/summary-complete.md 2>/dev/null

echo "finalize finished $(date)" >> "$LOGS/chain.log"
echo "0" > "$LOGS/finalize-complete.marker"
