#!/usr/bin/env bash
# Azure STT -> Gemini voice, against Gemini Live Translate, on the same audio.
#
#   bash run.sh <file with AZURE_SPEECH_KEY / AZURE_SPEECH_REGION>
#
# The env file is read only by the Azure step, in a subshell, so nothing in it
# reaches the Gemini steps. Gemini runs on Vertex with your gcloud login (the
# project from GOOGLE_CLOUD_PROJECT or `gcloud config`). Prints no secrets.
set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE="${1:?usage: bash run.sh <env file with the Azure Speech key>}"
DIRS="en-ja en-zh en-km en-lo en-ht ja-en zh-en km-en lo-en ht-en"

[ -f audio/en.wav ] || { echo "Make the audio first: python3 make_audio.py en ja zh; .venv/bin/python make_audio.py km lo ht"; exit 1; }

echo "== 1/4 Azure speech-to-text (real time, two clips at a time)"
( set -a; . "$ENV_FILE"; set +a; .venv/bin/python azure_stt.py en ja zh km lo ht )

TOK="$(gcloud auth print-access-token)" || { echo "gcloud login needed: run  gcloud auth login"; exit 1; }
export TOK
export GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-${VERTEX_PROJECT:-$(gcloud config get-value project 2>/dev/null)}}"

rm -rf out/pipe out/live out/judge  # graded side by side, so both run fresh
echo "== 2/4 Azure text -> Gemini voice (real time, ~3 min)"
node gemini_live.mjs pipe $DIRS
echo "== 3/4 Gemini Live Translate on the same audio (real time, ~3 min)"
node gemini_live.mjs live $DIRS
echo "== 4/4 Blind grading (Gemini 2.5 Pro)"
python3 judge.py $DIRS
