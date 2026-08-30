#!/usr/bin/env bash
# SI first so its labels exist, export them, then the main text twice.
set -euo pipefail
cd "$(dirname "$0")"
TECTONIC="${TECTONIC:-/path/to/user/anaconda3/envs/catdt/bin/tectonic}"
echo "==> si.tex"          ; "$TECTONIC" --keep-intermediates --keep-logs si.tex
echo "==> si-xr.tex"       ; python3 gen-si-xr.py
echo "==> main.tex pass 1" ; "$TECTONIC" --keep-intermediates --keep-logs main.tex
echo "==> main.tex pass 2" ; "$TECTONIC" --keep-intermediates --keep-logs main.tex
echo "==> main.pdf si.pdf"
