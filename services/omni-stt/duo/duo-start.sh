#!/usr/bin/env bash
# Two omni-stt processes on one GPU, behind one port (../README.md, "One GPU for both"):
#   :8081 finals    OMNI_CARD=$DUO_LISTEN_CARD (the 7B: the text of record)
#   :8082 streaming OMNI_CARD=$DUO_STREAM_CARD, STT_CTC_STREAM=1 (the 3B's live text)
#   :$PORT router.py: ?stream= goes to the streaming service, the rest to the finals
# Both load at once (their checkpoints are read in parallel). If any of the
# three exits, the others are stopped and the container exits non-zero.
#
# Every other omni-stt setting (STT_TOKEN, STT_SIGNING_KEY, STT_TOKEN_NONPROFIT,
# ENDPOINT_MS, ...) reaches both services from the environment. The ones that
# differ between them are set here:
#   DUO_LISTEN_STREAMS (6)  connections the finals service takes
#   DUO_STREAM_STREAMS (12) connections the streaming service takes
#   DUO_LISTEN_CARD (omniASR_LLM_7B_bf16), DUO_STREAM_CARD (omniASR_CTC_3B_bf16)
set -uo pipefail
cd "$(dirname "$0")" || exit 1
PORT="${PORT:-8080}"
LP="${DUO_LISTEN_PORT:-8081}"
SP="${DUO_STREAM_PORT:-8082}"
t0=$(date +%s)
echo "[duo] starting: finals on :$LP, streaming on :$SP, router on :$PORT"

PORT="$LP" OMNI_CARD="${DUO_LISTEN_CARD:-omniASR_LLM_7B_bf16}" STT_CTC_STREAM=0 STT_SERVE=listen \
  STT_MAX_CONNECTIONS="${DUO_LISTEN_STREAMS:-6}" OMNI_MMAP="${OMNI_MMAP:-1}" \
  python server.py > >(sed -u 's/^/[7b] /') 2>&1 &
p7=$!
card3="${DUO_STREAM_CARD:-omniASR_CTC_3B_bf16}"
PORT="$SP" OMNI_CARD="$card3" STT_CTC_CARD="$card3" STT_CTC_STREAM=1 STT_SERVE=listen \
  STT_MAX_CONNECTIONS="${DUO_STREAM_STREAMS:-12}" OMNI_MMAP="${OMNI_MMAP:-1}" \
  python server.py > >(sed -u 's/^/[3b] /') 2>&1 &
p3=$!
PORT="$PORT" DUO_LISTEN="127.0.0.1:$LP" DUO_STREAM="127.0.0.1:$SP" \
  python duo/router.py 2>&1 &
pr=$!

stop() { kill "$p7" "$p3" "$pr" 2>/dev/null; wait 2>/dev/null; }
trap 'stop; exit 143' TERM INT
wait -n "$p7" "$p3" "$pr"
code=$?
echo "[duo] a process exited ($code) $(( $(date +%s) - t0 )) s after start; stopping the others"
stop
exit $(( code == 0 ? 1 : code ))
