#!/usr/bin/env bash
# ElevenLabs, both halves. Needs only the ElevenLabs key; scoring uses no key.
#   bash run.sh <file with the key: an env file with ELEVENLABS_API_KEY=, or a
#               text file with the bare sk_ key on its own line>
# 1. Scribe v2 Realtime on the real-voice clips (Haitian Creole first: the gap
#    Azure leaves), told the language and not; scored beside Azure, Gemini
#    transcribe-live and Omnilingual.
# 2. The room voice: Flash v2.5 (fastest; 32 languages) and v4 Turbo (94,
#    adds fa and lo) — first-audio delay per language, readings saved.
#    Neither lists Haitian Creole or Khmer; they are read anyway and marked.
set -euo pipefail
cd "$(dirname "$0")"
F="${1:?usage: bash run.sh <file with the ElevenLabs key>}"
if grep -q '^ELEVENLABS_API_KEY=' "$F"; then
  ELEVENLABS_API_KEY="$(grep '^ELEVENLABS_API_KEY=' "$F" | tail -1 | cut -d= -f2- | tr -d "\"' \r")"
else
  ELEVENLABS_API_KEY="$(grep -E '^sk_' "$F" | tail -1 | tr -d ' \r')"
fi
[ -n "$ELEVENLABS_API_KEY" ] || { echo "No key found in $F"; exit 1; }
export ELEVENLABS_API_KEY
(cd ../2026-10-real-voices && node elevenlabs_stt.mjs ht fr en ja km lo && node elevenlabs_stt.mjs --auto ht)
(cd ../2026-10-real-voices && python3 score_transcribe_live.py)
node elevenlabs_tts.mjs es en ja ht fr fa km lo
ELEVENLABS_MODEL=eleven_v4_turbo node elevenlabs_tts.mjs es en ja ht fr fa km lo
