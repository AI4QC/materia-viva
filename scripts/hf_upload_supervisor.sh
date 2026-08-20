#!/usr/bin/env bash
# Keep `hf upload-large-folder` alive until the dataset repo actually has the
# index. Restart it whenever it stalls.
#   setsid nohup bash scripts/hf_upload_supervisor.sh &
#
# Why this exists: the upload egresses through a proxy tunnel (Mihomo). When
# that connection drops, the uploader's worker threads block on a socket with
# no timeout -- the process stays alive at ~9% CPU redrawing the same progress
# bars, with zero bytes read, written or sent, forever. A 44 GB transfer over
# hours will hit that repeatedly, so "did it move at all in the last N minutes"
# is the only liveness signal worth trusting.
#
# Restarting is cheap: upload-large-folder keeps its state under
# <folder>/.cache/huggingface/upload/ and resumes rather than re-sending.
set -u
cd "$(dirname "$0")/.."
OUT=/tmp/local-workspace
LOG="$OUT/hf-upload.log"
STATE="$OUT/hf-supervisor.log"
FOLDER=data/hf-upload
REPO=AI4QC/MateriaViva
PY=/path/to/user/anaconda3/envs/matgenbench-py310/bin/python

#: no progress for this long -> assume the tunnel died and restart
STALL_SECONDS=600
POLL=60

IFACE=$(ip route get 1.1.1.1 2>/dev/null | grep -oP 'dev \K\S+' | head -1)
tx() { cat "/sys/class/net/$IFACE/statistics/tx_bytes" 2>/dev/null || echo 0; }

remote_has_index() {
  $PY - <<'PYEOF' 2>/dev/null
from huggingface_hub import HfApi
try:
    i = HfApi().repo_info("AI4QC/MateriaViva", repo_type="dataset")
    names = {s.rfilename for s in (i.siblings or [])}
    need = {"index/materials.sqlite", "index/structures.blob", "index/curves.blob"}
    raise SystemExit(0 if need <= names else 1)
except SystemExit:
    raise
except Exception:
    raise SystemExit(1)
PYEOF
}

echo "supervisor started $(date)" >> "$STATE"
attempt=0
while true; do
  if remote_has_index; then
    echo "supervisor: index present on $REPO, done $(date)" >> "$STATE"
    echo "0" > "$OUT/hf-upload-complete.marker"
    exit 0
  fi

  attempt=$((attempt + 1))
  echo "supervisor: launching attempt $attempt $(date)" >> "$STATE"
  hf upload-large-folder "$REPO" "$FOLDER" --repo-type=dataset --private \
      >> "$LOG" 2>&1 &
  UP=$!

  last_tx=$(tx); last_move=$(date +%s)
  while kill -0 "$UP" 2>/dev/null; do
    sleep "$POLL"
    now_tx=$(tx); now=$(date +%s)
    # Any egress at all counts as alive. The uploader also reads heavily while
    # xet chunks the files, so fall back to rchar when the network is briefly
    # idle for a legitimate reason.
    rchar=$(awk '/^rchar/{print $2}' "/proc/$UP/io" 2>/dev/null || echo 0)
    if [ "$now_tx" -gt $((last_tx + 262144)) ] || [ "${rchar:-0}" -gt "${last_rchar:-0}" ]; then
      last_move=$now
    fi
    last_tx=$now_tx; last_rchar=${rchar:-0}
    if [ $((now - last_move)) -ge "$STALL_SECONDS" ]; then
      echo "supervisor: stalled ${STALL_SECONDS}s, restarting $(date)" >> "$STATE"
      kill -9 "$UP" 2>/dev/null
      sleep 5
      break
    fi
  done
  wait "$UP" 2>/dev/null
  sleep 10
done
