#!/usr/bin/env bash
# Gladia's transcription of the synthetic clips, the only new step: the other
# three systems' outputs are kept. Then Claude (or you) runs:
#   node gemini_live.mjs gladia ...  and  python3 judge.py ...
#   bash run_gladia.sh <env file with GLADIA_API_KEY>
set -euo pipefail
cd "$(dirname "$0")"
( set -a; . "${1:?usage: bash run_gladia.sh <env file with GLADIA_API_KEY>}"; set +a; node gladia_stt.mjs en ja zh km lo ht )
