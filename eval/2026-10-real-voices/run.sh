#!/usr/bin/env bash
# Real voices (FLEURS; CMU for Haitian Creole): Azure alone, Azure STT ->
# Gemini, Gladia STT -> Gemini and Gemini Live, graded side by side against
# each clip's references.
#   bash run.sh <Azure env file> <Gladia env file>
# Each env file is read only by its own step, in a subshell. Gemini runs on
# Vertex with your gcloud login and project. Prints no secrets.
set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE="${1:?usage: bash run.sh <Azure env file> <Gladia env file>}"
GLADIA_ENV="${2:?usage: bash run.sh <Azure env file> <Gladia env file>}"
[ -f audio/en.wav ] || { echo "Fetch the audio first: .venv/bin/python fetch_audio.py && python3 make_refs.py"; exit 1; }
[ -d node_modules ] || npm install --silent >/dev/null 2>&1 || true

echo "== 0/5 Gladia speech-to-text (real time, two clips at a time)"
( set -a; . "$GLADIA_ENV"; set +a; node gladia_stt.mjs en ja km lo ht )
echo "== 1/5 Azure speech-to-text (real time, two clips at a time)"
( set -a; . "$ENV_FILE"; set +a; .venv/bin/python azure_stt.py en ja km lo )
echo "== 2/5 Azure alone: speech translation + voice timing"
( set -a; . "$ENV_FILE"; set +a; .venv/bin/python azure_translate.py en ja km lo )

TOK="$(gcloud auth print-access-token)" || { echo "gcloud login needed: run  gcloud auth login"; exit 1; }
export TOK GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
echo "== 3/5 Azure text -> Gemini voice"
node gemini_live.mjs pipe en-ja en-km en-lo en-ht ja-en km-en lo-en
echo "== 3b/5 Gladia text -> Gemini voice (Haitian Creole speakers included)"
node gemini_live.mjs gladia en-ja en-km en-lo en-ht ja-en km-en lo-en ht-en
echo "== 4/5 Gemini Live Translate on the same audio"
node gemini_live.mjs live en-ja en-km en-lo en-ht ja-en km-en lo-en ht-en
echo "== 5/5 Blind grading, all three side by side"
rm -rf out/judge
python3 judge.py en-ja en-km en-lo en-ht ja-en km-en lo-en ht-en
