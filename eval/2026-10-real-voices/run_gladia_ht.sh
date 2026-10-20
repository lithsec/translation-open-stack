#!/usr/bin/env bash
# Haitian Creole only, real voices (CMU speakers): Gladia's transcription, the
# one step that needs the Gladia key. Then Gemini on its text, Gemini Live on
# the audio, and the grade (gcloud).
#   bash run_gladia_ht.sh <env file with GLADIA_API_KEY>
set -euo pipefail
cd "$(dirname "$0")"
( set -a; . "${1:?usage: bash run_gladia_ht.sh <env file with GLADIA_API_KEY>}"; set +a; node gladia_stt.mjs ht )
