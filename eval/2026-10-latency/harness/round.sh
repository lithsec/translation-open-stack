#!/bin/bash
# One full round: every route x direction, in two batches of parallel sessions.
#   round.sh <scratch LT dir> <clipDir> <tag> <outDir>
lt=$1; clips=$2; tag=$3; out=$4
mkdir -p "$out"
"$lt/harness/launch.sh" "$clips" "$out" "$tag" "azure-foundry en es" "azure-gemini en es" "azure-gemini-stream en es" "gemini-lt en es" \
  "azure-foundry en ja" "azure-gemini en ja" "azure-gemini-stream en ja" "gemini-lt en ja" "ht-voice-gemini en ht" "ht-voice-coqui en ht" "gemini-lt en ht"
"$lt/harness/launch.sh" "$clips" "$out" "$tag" "azure-foundry es en" "azure-gemini es en" "azure-gemini-stream es en" "gemini-lt es en" \
  "azure-foundry km en" "azure-gemini km en" "azure-gemini-stream km en" "gemini-lt km en" "ht-exception ht en" "gemini-lt ht en"
