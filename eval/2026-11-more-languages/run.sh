#!/usr/bin/env bash
# The round on the pod, after setup.sh:  A (the stack as configured, one direction at a time, sets a and b),
# then B (the seven Hy-MT2-only languages on Gemma, sets a and b at once), then the analysis, then stop the pod.
#   nohup bash run.sh > /workspace/work/run.log 2>&1 &
set -uo pipefail
H=/workspace/tos/eval/2026-11-more-languages; W=/workspace/work
until grep -q "setup done" $W/setup.log 2>/dev/null; do sleep 15; done
grep -q "^done" $W/build.log || { echo "clips failed"; tail $W/build.log; exit 1; }
node -e 'if (typeof WebSocket === "undefined") process.exit(1)' || { echo "node has no WebSocket"; exit 1; }
ALL=""; for l in zh uk vi ar fa tl sw it ko id tr bn ur hi; do ALL="$ALL,$l-en,en-$l"; done; ALL=${ALL#,}
H7=""; for l in it ko id tr bn ur hi; do H7="$H7,$l-en,en-$l"; done; H7=${H7#,}
bash $H/live.sh A A a:$W/clips_a:$ALL b:$W/clips_b:$ALL
touch $W/PHASE_A.done
PAR=1 bash $H/live.sh B B a:$W/clips_a:$H7 b:$W/clips_b:$H7
touch $W/PHASE_B.done
bash $H/analyze.sh $W
touch $W/PHASE_analyze.done
echo "$(date -u +%T) all done; stopping in 20 min unless /workspace/KEEP exists"
sleep 1200
[ -e /workspace/KEEP ] || bash $H/../2026-11-commercial-edition/results/lao-gemma/deadline.sh 0
