#!/usr/bin/env bash
# The whole stack on CPU with stand-in models, restart-safe, then the FULL
# bench against it — fanout concurrency and X->eng both. This must be green
# before any GPU is rented: the first GPU session burned $1.30 discovering
# that every one of its failures (PEP 668, IPv6 localhost, stdout buffering,
# a stale process serving old code) was environmental and findable here for
# free.
#
#   bash tools/dev-cpu.sh [python]          # default: python3
#
# Needs an English 24 kHz mono WAV for the fanout run (WAV=..., default
# /tmp/xeng-src/en.wav) and a folder of <lang>.wav source clips for X->eng
# (/tmp/xeng-src). Any short FLEURS clip works, e.g.
#   ffmpeg -i clip.flac -ar 24000 -ac 1 /tmp/xeng-src/en.wav
#
# Stand-ins prove PLUMBING, not quality: whisper tiny both slots, t5-small for
# MT (emits junk text by design — it does not know MADLAD's language tags).
set -euo pipefail
PY="${1:-python3}"
DIR="$(cd "$(dirname "$0")" && pwd)"   # tools/ (bench.py)
ROOT="$(cd "$DIR/.." && pwd)"          # the repository (server/)
RUN=/tmp/lithos-stack-dev
mkdir -p "$RUN"

# ---- restart-safe start: the old process is GONE before the new one starts.
# The GPU session lost half an hour to a stale server that kept running old
# code through two rounds of diagnosis. Never again: kill by pidfile, verify.
if [ -f "$RUN/server.pid" ] && kill -0 "$(cat "$RUN/server.pid")" 2>/dev/null; then
  kill "$(cat "$RUN/server.pid")"
  for _ in $(seq 1 20); do kill -0 "$(cat "$RUN/server.pid")" 2>/dev/null || break; sleep 0.5; done
  kill -0 "$(cat "$RUN/server.pid")" 2>/dev/null && { echo "old server would not die"; exit 1; }
fi

"$PY" -u "$ROOT/server/server.py" \
  --langs es,fr,pt,sw,ht,km,lo \
  --asr-model tiny --asr-multi-model tiny --mt-model t5-small \
  --mms --xeng --srcs en,es,fr,pt,sw,km,lo \
  --port 8791 > "$RUN/server.log" 2>&1 &
echo $! > "$RUN/server.pid"

echo "waiting for ready…"
for _ in $(seq 1 60); do
  grep -q "ready on" "$RUN/server.log" 2>/dev/null && break
  kill -0 "$(cat "$RUN/server.pid")" 2>/dev/null || { echo "SERVER DIED:"; tail -12 "$RUN/server.log"; exit 1; }
  sleep 2
done
grep -q "ready on" "$RUN/server.log" || { echo "never became ready:"; tail -12 "$RUN/server.log"; exit 1; }
grep -m1 "ready on" "$RUN/server.log"

fail=0
echo; echo "===== FANOUT: 5 languages, concurrent ====="
# km/lo are absent ON PURPOSE: their MMS tokenizers are Khmer/Lao-script only,
# and the t5-small stand-in can only emit Latin junk — so they can never
# produce audio here. The MMS path itself is proven separately with real-script
# text; on the GPU, MADLAD emits the real scripts and the full 7 run.
"$PY" -u "$DIR/bench.py" --host 127.0.0.1 --port 8791 --mode fanout \
  --wav "${WAV:-/tmp/xeng-src/en.wav}" \
  --langs es,fr,pt,sw,ht --out "$RUN/fanout" || fail=1

echo; echo "===== X->ENG: six sources ====="
"$PY" -u "$DIR/bench.py" --host 127.0.0.1 --port 8791 --mode xeng \
  --srcdir /tmp/xeng-src --srcs es,fr,pt,sw,km,lo --out "$RUN/xeng" || fail=1

echo; echo "===== server still alive after both? ====="
if kill -0 "$(cat "$RUN/server.pid")" 2>/dev/null; then
  echo "yes — survived the full bench"
else
  echo "NO — it died during the bench:"; tail -12 "$RUN/server.log"; fail=1
fi

kill "$(cat "$RUN/server.pid")" 2>/dev/null || true
[ $fail -eq 0 ] && echo "CPU BENCH GREEN — a GPU run is now just two model flags." || echo "NOT GREEN — fix before renting anything."
exit $fail
