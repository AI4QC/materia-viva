#!/usr/bin/env bash
# Everything the paper needs re-derived once NOMAD is in the database.
#   setsid nohup bash scripts/properties/nomad_reanalysis_chain.sh &
#
# Waits for the ingestion chain, then rebuilds both analysis layers so that no
# figure describes a pre-NOMAD corpus while another describes a post-NOMAD one:
#   A  scripts/ml   -> task census and gated prediction sets (Figure 4 reads these)
#   B  paper/figure_scripts --extract -> every CSV behind Figures 1-3, then all figures
#
# export_structures.py is deliberately skipped: it writes 6 GB of atom shards
# needed to train models, not to draw any figure in the paper.
set -u
cd "$(dirname "$0")/../.."
P=/path/to/user/anaconda3/envs/matgenbench-py310/bin/python
LOGS=data/props_work/_logs
mkdir -p "$LOGS"
LOG="$LOGS/nomad-reanalysis.log"
say() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

say "waiting for the ingestion chain"
for i in $(seq 1 720); do
  [ -f "$LOGS/nomad-complete.marker" ] && break
  sleep 60
done
[ -f "$LOGS/nomad-complete.marker" ] || { say "ingestion never completed, stopping"; exit 1; }
say "=== re-analysis start ==="

say "A1 property census"
$P scripts/ml/property_census.py --out data/ml/census >> "$LOG" 2>&1 \
  || { say "census FAILED"; exit 1; }

say "A1b trainable tasks (property x level of theory)"
$P scripts/ml/task_census.py --out data/ml/census >> "$LOG" 2>&1 \
  || { say "task_census FAILED"; exit 1; }

say "A2 export targets"
$P scripts/ml/export_targets.py --out data/ml/export >> "$LOG" 2>&1 \
  || { say "export_targets FAILED"; exit 1; }

say "A3 tensors"
$P scripts/ml/extract_tensors.py jarvis --out data/ml/export/tensors >> "$LOG" 2>&1 || true
$P scripts/ml/extract_tensors.py phonondb --out data/ml/export/tensors --workers 16 >> "$LOG" 2>&1 || true

say "A4 training sets"
$P scripts/ml/make_training_sets.py --export data/ml/export --out data/ml/datasets \
  >> "$LOG" 2>&1 || { say "make_training_sets FAILED"; exit 1; }

say "A5 prediction sets"
$P scripts/ml/prediction_sets.py --export data/ml/export --datasets data/ml/datasets \
    --out data/ml/predict --gate strict >> "$LOG" 2>&1 \
  || { say "prediction_sets FAILED"; exit 1; }

say "B  paper extraction + figures"
$P paper/figure_scripts/generate_all.py --extract >> "$LOG" 2>&1 \
  || { say "paper regeneration FAILED"; exit 1; }

say "=== re-analysis complete ==="
touch "$LOGS/nomad-reanalysis-complete.marker"
