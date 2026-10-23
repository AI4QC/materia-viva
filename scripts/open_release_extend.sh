#!/usr/bin/env bash
# Add the property values and curves of the open structures to the open release,
# restage both dataset cards, then hand over to the upload service.
#
# Runs as a transient user unit so no terminal or Claude session owns it:
#
#   systemd-run --user --unit=materiaviva-open-extend --collect \
#       -p WorkingDirectory=$PWD -E PY=/path/to/python bash scripts/open_release_extend.sh
#   journalctl --user -u materiaviva-open-extend -f
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python}      # needs numpy + pyarrow

$PY scripts/export_open_structures.py properties
$PY scripts/export_open_structures.py curves
$PY scripts/export_open_structures.py card
$PY scripts/make_dataset_card.py --out data/hf-upload/README.md

rm -f data/hf-release-logs/DONE
systemctl --user start materiaviva-hf-upload
echo "export done; upload service started"
