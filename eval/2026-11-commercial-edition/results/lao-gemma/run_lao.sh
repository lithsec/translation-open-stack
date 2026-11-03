#!/usr/bin/env bash
# Pod side, after setup.sh: ../../live.sh (one commercial stack start, lo-en then en-lo per set, as the November
# round), then ../../analyze.sh. The stack starts at once, beside vLLM's first install/compile; the runs wait
# until the stack logs that Gemma 4 answers (live.sh's own wait, 200 s, lengthened to 40 min in a pod-only copy
# so no Lao sentence goes to the fallback translator while vLLM is still compiling).
#   bash run_lao.sh     -> /workspace/work/e2e_G_{a,b}/out/{runs,latency.json,sentences.json}
set -uo pipefail
C=/workspace/tos-commercial/eval/2026-11-commercial-edition; W=/workspace/work
until grep -q "setup done" $W/setup.log; do sleep 10; done
rm -rf $W/e2e_G_a $W/e2e_G_b
# (live.sh's pattern also matches the "not answering —" line, which is harmless when Gemma is already up, as in
# the November round; here it is not, so the copy waits for the Gemma line that names lo.)
sed 's/seq 1 40); do grep -q "llmmt: .\* answering —"/seq 1 480); do grep -qE "llmmt: .*\\) answering — .*lo"/' $C/live.sh > $C/.live_wait.sh
grep -q "seq 1 480" $C/.live_wait.sh || { echo "live.sh copy not patched"; exit 1; }
# the e2e client needs Node's global WebSocket (Node 22); the image's apt nodejs is 18
node -e 'if (typeof WebSocket === "undefined") process.exit(1)' || { echo "node $(node --version) has no WebSocket"; exit 1; }
bash $C/.live_wait.sh commercial G a:$W/seta/clips_reg:lo-en,en-lo b:$W/setb/clips_reg:lo-en,en-lo
grep -E "llmmt.*(fail|answering)|pipeline behind|dropped" $W/stack_G.log | tail -n 20
bash $C/analyze.sh $W
echo "$(date -u +%T) all done"
