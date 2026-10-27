#!/usr/bin/env bash
# load.sh NAME S7 SCTC [LIMIT]: S7 streams on the 7B and SCTC streaming ones (each half km, half lo), all
# through the duo router on :8080, LIMIT clips each (10). Clips: prep_fleurs.py's set in SET (/opt/set).
# Results and the GPU trace (nvidia-smi, once a second) in OUT/NAME (/opt/res).
set -u
cd "$(dirname "$0")/../2026-10-ctc-stream" || exit 1
N=$1; S7=$2; SC=$3; L=${4:-10}
U=ws://127.0.0.1:8080/listen; SET=${SET:-/opt/set}; R=${OUT:-/opt/res}/$N
mkdir -p "$R"
nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used --format=csv,noheader,nounits -l 1 > "$R/gpu.csv" &
g=$!
pids=()
if [ "$SC" -gt 0 ]; then
  python eval_client.py "$U" "$SET" km "$R/ctc_km.json" --lookahead 2 --streams $((SC / 2)) --limit "$L" & pids+=($!)
  python eval_client.py "$U" "$SET" lo "$R/ctc_lo.json" --lookahead 2 --streams $((SC - SC / 2)) --limit "$L" & pids+=($!)
fi
if [ "$S7" -gt 0 ]; then
  python eval_client.py "$U" "$SET" km "$R/b7_km.json" --nostream --streams $((S7 / 2)) --limit "$L" & pids+=($!)
  python eval_client.py "$U" "$SET" lo "$R/b7_lo.json" --nostream --streams $((S7 - S7 / 2)) --limit "$L" & pids+=($!)
fi
wait "${pids[@]}"
kill "$g"
python -I score_stream.py "$SET" "$R"/*.json > "$R/score.txt" 2>&1
head -n -1 "$R/score.txt"
awk -F', ' '{u+=$2; if($2>mu)mu=$2; if($3>mm)mm=$3; n++} END {printf "gpu util mean %.0f%% max %d%%, mem max %d MiB over %d s\n", u/n, mu, mm, n}' "$R/gpu.csv"
