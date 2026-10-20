#!/usr/bin/env bash
# Azure alone (speech translation + its voices) on the same clips, then all
# three contenders graded side by side.
#   bash run_azure_only.sh <env file with AZURE_SPEECH_KEY / AZURE_SPEECH_REGION>
set -euo pipefail
cd "$(dirname "$0")"
ENV_FILE="${1:?usage: bash run_azure_only.sh <env file with the Azure Speech key>}"
echo "== 1/2 Azure speech translation (real time, two clips at a time, ~5 min)"
( set -a; . "$ENV_FILE"; set +a; .venv/bin/python azure_translate.py en ja zh km lo )
echo "== 2/2 Blind grading, all three side by side (Gemini 2.5 Pro)"
TOK="$(gcloud auth print-access-token)" || { echo "gcloud login needed: run  gcloud auth login"; exit 1; }
export TOK GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
rm -rf out/judge  # graded side by side, so all three again
python3 judge.py en-ja en-zh en-km en-lo en-ht ja-en zh-en km-en lo-en ht-en
