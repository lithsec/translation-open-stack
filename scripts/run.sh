#!/usr/bin/env bash
# Start the stack the way it is actually measured and run. Every flag here was
# chosen against a number, not a preference — see docs/dev/lessons-learned.md,
# "Latency and throughput".
#
#   EDITION=nonprofit|commercial bash scripts/run.sh [langs] [srcs]
#
# EDITION picks the voices whose licences fit the deployment (docs/licences.md §2):
#   nonprofit  (default) every configured voice, including Meta's MMS (CC-BY-NC)
#              for Haitian Creole and the non-commercial Piper voices.
#   commercial only what server/licences.py classifies as commercially usable:
#              no ⛔ voice or model ever loads, ❓ ones only with a
#              [licence_review] entry; the [<lang>.commercial] voices replace the
#              others (Coqui OpenBible for Haitian Creole, VoxCPM2 for ko tr ru ar
#              id sw vi); fa and ro get eSpeak NG only. The server enforces it
#              (--edition); check first: python3 server/stack_config.py check --edition commercial
# VoxCPM2 (Apache 2.0) speaks its languages when prepare-voices.sh has installed
# it; otherwise their fallback voice (MMS in nonprofit, eSpeak NG) or text only.
# In commercial it runs one instance per GPU by default (VOXCPM_INSTANCES, below).
# VOICES_DIR (default /workspace/voices): the Piper voices, as fetch-voices.sh puts them.
# STACK_TOKEN, if set, is required from every client (Authorization: Bearer <token>;
# see docs/dev/protocol.md).
#
# Reads models from the warm cache on /workspace, so on a pod with the network
# volume attached this starts in about a minute.
set -euo pipefail
# STACK_HOME: where models, voices and caches live (a pod's volume; a folder on a Mac).
W="${STACK_HOME:-/workspace}"
# RunPod's PyTorch image sets HF_HUB_ENABLE_HF_TRANSFER=1 without the hf_transfer package,
# and then EVERY Hugging Face download fails ("hf_transfer ... not available"). That quietly
# disabled language ID on launcher-started pods: every source was served as English (2026-09-29).
python3 -c "import hf_transfer" 2>/dev/null || export HF_HUB_ENABLE_HF_TRANSFER=0
DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$DIR/.." && pwd)"   # the repository: server/ lives there
# STACK_PROFILE: the hardware profile's script defaults (profiles/<name>.toml [env]).
# shellcheck source=profile-env.sh
. "$DIR/profile-env.sh"
LANGS="${1:-${LANGS:-en,es,fr,pt,de,ru,uk,zh,ja,km,lo,ht,ar,hi,vi,ko,tl,fa,id,tr,bn,ur,it,sw,ro}}"
SRCS="${2:-${SRCS:-en,es,fr,pt,de,ru,uk,it,zh,ja,ko,sw,km,lo,ht,ar,hi,vi,tl,fa,id,tr,bn,ur,ro}}"
export HF_HOME="${HF_HOME:-$W/hf-cache}"
# Less fragmentation: the default allocator holds on to blocks it cannot reuse, and the full stack
# (25 languages + VoxCPM2) sits right at a 32 GB card's limit.
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
# VoxCPM2: one sentence per instance at once (what a service runs; see below). Set before
# `check` so it reports the same number.
export VOXCPM_MAX_INFLIGHT="${VOXCPM_MAX_INFLIGHT:-1}"
EDITION="${EDITION:-nonprofit}"
case "$EDITION" in
  nonprofit)  VOICE_ARGS=(--mms) ;;
  commercial) VOICE_ARGS=(--coqui) ;;
  *) echo "EDITION must be nonprofit or commercial (got '$EDITION')" >&2; exit 1 ;;
esac
echo "edition: $EDITION"
# What this edition serves, per language, with licences (and a non-zero exit if
# commercial would load a model it may not): printed before anything loads.
python3 "$ROOT/server/stack_config.py" check --edition "$EDITION"

# Models and revisions: languages.toml [models] (docs/user-guide.md, "Replace a model or a revision").
cfg() { python3 "$ROOT/server/stack_config.py" get "$1"; }
ASR_MODEL="$(cfg models.whisper.model)"
ASR_MULTI="$(cfg models.whisper.multi_model)"
ASR_ARGS=(--asr-model "$ASR_MODEL" --asr-multi-model "${ASR_MULTI:-$ASR_MODEL}" --asr-revision "$(cfg models.whisper.revision)"
          --asr-multi-revision "$(cfg models.whisper.multi_revision)")
# A translator built from another revision than languages.toml names: say so
# (prepare-mt.sh rebuilds it; runpod-start.sh and the Docker entrypoint run it first).
stamp() {
  local want; want="$(cfg "models.$2.repo") @ $(cfg "models.$2.revision")"
  if [ -f "$1/PROVENANCE.txt" ] && [ "$(head -1 "$1/PROVENANCE.txt")" != "$want" ]; then
    echo "WARNING: $1 was built from '$(head -1 "$1/PROVENANCE.txt")', languages.toml asks for '$want': run scripts/prepare-mt.sh" >&2
  fi
  return 0
}

# Translation: Hy-MT2 for the 36 languages it supports, MADLAD 7B for the rest,
# both built by prepare-mt.sh. Falls back to the older MADLAD 3B if not built yet.
MT_ARGS=()
# MADLAD=3b: the smaller fallback translator, to fit a 32 GB card (docs/user-guide.md,
# "Fitting a 32 GB card"): ~5 GB less, at some cost to Swahili and Haitian Creole.
if [ "${MADLAD:-7b}" = 3b ] && [ -f "$W/madlad-ct2/model.bin" ]; then
  MT_ARGS+=(--mt-ct2 "$W/madlad-ct2"); stamp "$W/madlad-ct2" madlad3b
elif [ -f "$W/mt/madlad7b-ct2/model.bin" ]; then
  MT_ARGS+=(--mt-ct2 "$W/mt/madlad7b-ct2"); stamp "$W/mt/madlad7b-ct2" madlad
elif [ -f "$W/madlad-ct2/model.bin" ]; then
  echo "note: MADLAD 7B not built (bash scripts/prepare-mt.sh) — using MADLAD 3B"
  MT_ARGS+=(--mt-ct2 "$W/madlad-ct2"); stamp "$W/madlad-ct2" madlad3b
else
  echo "note: no CTranslate2 model — MT will run through transformers (slower)"
fi
if [ -f "$W/mt/hymt2-7b-nf4/config.json" ]; then
  MT_ARGS+=(--hymt "$W/mt/hymt2-7b-nf4"); stamp "$W/mt/hymt2-7b-nf4" hymt
else
  echo "note: Hy-MT2 not built (bash scripts/prepare-mt.sh) — MADLAD translates every language"
fi

# VoxCPM2 voice services, from their own venv on the volume: one instance per GPU the plan
# gives it (server/stack_config.py voxcpm_plan). One instance makes ~2-3 real-time voices, and
# commercial routes ten languages to it, so there:
#   VOXCPM_INSTANCES=auto (the commercial default): one on the main GPU (GPU 0, with the rest of
#     the stack) plus one on each other GPU with >= 10 GB, up to VOXCPM_MAX_INSTANCES (4);
#     "1" is the nonprofit default (today's single instance), "0" = none (like VOXCPM=0);
#   VOXCPM_GPUS=0,1,1: exactly these GPUs, in order (here two instances share GPU 1);
#   VOXCPM_MAX_INFLIGHT (1): sentences one instance takes at once. A service makes one voice
#     at a time and answers 503 rather than queue, so more only hides a queue in the service.
#     With every instance full a sentence waits in the server for the first free one, up to
#     VOXCPM_QUEUE_S (2 s), then goes to the next voice in its chain (eSpeak NG at the end of
#     every commercial chain); with no voice after VoxCPM2 (km lo tl) up to VOXCPM_WAIT_S (15 s).
# Instances listen on 8791, 8792, ...; the server gets every URL that came up.
VOXCPM_VENV="${VOXCPM_VENV:-$W/venv_voxcpm}"
VOXCPM_LOG="${VOXCPM_LOG:-$W/voxcpm.log}"
# nvidia-smi numbers GPUs by PCI bus, CUDA by default fastest first: make CUDA_VISIBLE_DEVICES mean
# the same GPU to both.
export CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}"
vox_health() { curl -sf -m 5 "http://127.0.0.1:$1/health" >/dev/null 2>&1; }
vox_running() { pgrep -f "server/voxcpm_service[.]py --port $1( |\$)" >/dev/null; }
vox_log() { if [ "$1" = 8791 ]; then echo "$VOXCPM_LOG"; else echo "${VOXCPM_LOG%.log}-$1.log"; fi; }
if [ "${VOXCPM:-1}" = 1 ] && [ -x "$VOXCPM_VENV/bin/python" ]; then
  VOX_PLAN="$(python3 "$ROOT/server/stack_config.py" voxcpm-plan --edition "$EDITION")"
  VOX_PORTS=()
  VOX_STARTED=$SECONDS
  while read -r gpu port; do
    [ -n "$port" ] || continue
    VOX_PORTS+=("$port")
    # Already running (e.g. the server alone was restarted)? A busy service can miss a quick
    # health check, so look for the process too, or a second copy loads and wastes ~7 GB.
    if vox_running "$port" || vox_health "$port"; then
      echo "VoxCPM2 on :$port already running"
      continue
    fi
    # languages.toml [models.voxcpm]; VOXCPM_REV in the environment wins. The instances start
    # together and warm up in parallel.
    if [ "$gpu" = - ]; then dev=(); else dev=(env "CUDA_VISIBLE_DEVICES=$gpu"); fi
    HF_HUB_OFFLINE=1 "${dev[@]}" "$VOXCPM_VENV/bin/python" -u "$ROOT/server/voxcpm_service.py" --port "$port" \
      --repo "$(cfg models.voxcpm.repo)" \
      --revision "${VOXCPM_REV:-$(cfg models.voxcpm.revision)}" > "$(vox_log "$port")" 2>&1 &
    echo "starting VoxCPM2 on :$port, GPU ${gpu/-/(default)} (log: $(vox_log "$port"))"
  done <<< "$VOX_PLAN"
  # Warm-up compiles kernels: ~2 min on a fast host, measured 472 s on a slow one (2026-09-29).
  # Capped at 10 min for all of them together, by the clock (a count of rounds overran: each
  # health check may take 5 s per port): the Lithos launcher gives a pod 25 min to report
  # ready, models included. The cap may be passed by at most one health check (5 s).
  # An instance that is neither healthy nor still running is given up on.
  # The first minute counts as "starting" even when pgrep can't see the process yet: right
  # after `&` it may still be the forked shell or `env`, and taking that for "gone" made
  # run.sh give up on every instance at once and serve without VoxCPM2 (2026-09-29).
  VOX_DEADLINE=$((VOX_STARTED + 600))
  while [ "$SECONDS" -lt "$VOX_DEADLINE" ]; do
    waiting=0
    young=$(( SECONDS - VOX_STARTED < 60 ))
    for port in "${VOX_PORTS[@]}"; do
      [ "$SECONDS" -ge "$VOX_DEADLINE" ] && break
      vox_health "$port" || { { vox_running "$port" || [ "$young" = 1 ]; } && waiting=1; }
    done
    [ "$waiting" = 0 ] && break
    sleep 2
  done
  VOX_URLS=()
  for port in "${VOX_PORTS[@]}"; do
    if vox_health "$port"; then VOX_URLS+=("http://127.0.0.1:$port")
    else echo "note: VoxCPM2 on :$port did not start (see $(vox_log "$port"))"; fi
  done
  if [ "${#VOX_URLS[@]}" -gt 0 ]; then
    # The plan said "VoxCPM2: N instances (GPU 0, GPU 1)" above; this is what came up.
    [ "${#VOX_URLS[@]}" -lt "${#VOX_PORTS[@]}" ] && echo "VoxCPM2: only ${#VOX_URLS[@]} of ${#VOX_PORTS[@]} instances up"
    [ "${#VOX_URLS[@]}" = 1 ] && echo "VoxCPM2: 1 instance serving; overflow → fallback voices"
    VOICE_ARGS+=(--voxcpm "$(IFS=,; echo "${VOX_URLS[*]}")")
    # Which languages it speaks: `voxcpm = true` in languages.toml for the edition, or VOXCPM_LANGS.
    [ -n "${VOXCPM_LANGS:-}" ] && VOICE_ARGS+=(--voxcpm-langs "$VOXCPM_LANGS")
  elif [ "${#VOX_PORTS[@]}" -gt 0 ]; then
    echo "note: VoxCPM2 did not start (see $VOXCPM_LOG) — its languages use the fallback voice or text"
  fi
fi

# eSpeak NG: the last voice of every language it speaks (VoxCPM2's overflow; fa and ro in
# commercial). A separate process per sentence (GPL-3.0, run, not linked: docs/licences.md §8).
if [ "${ESPEAK:-1}" = 1 ]; then
  if command -v espeak-ng >/dev/null; then VOICE_ARGS+=(--espeak)
  else echo "note: espeak-ng not installed — no last-resort voice (VoxCPM2 overflow is silent; fa, ro text only)"; fi
fi

[ -n "${STACK_TOKEN:-}" ] && echo "access token required (STACK_TOKEN set)"

# Refuse to start on a port something else already holds: a second server binds
# nothing, logs "address already in use", and leaves the OLD build serving while
# everything looks fine. That cost a debugging round.
if command -v lsof >/dev/null && lsof -ti tcp:8790 >/dev/null 2>&1; then
  echo "port 8790 is already in use by pid $(lsof -ti tcp:8790) — stop it first" >&2
  exit 1
fi

# --asr-model large-v3 (languages.toml [models.whisper]): +0.20s for proper nouns and
#   capitalisation, and it REPLACES the multilingual model rather than adding one
#   (multi_model = "" passes the same name), so VRAM goes down.
# --endpoint-ms 900: +0.20s, fewer sentences cut mid-thought.
# --max-utterance-s 12: only bites on genuinely unbroken speech.
exec python3 -u "$ROOT/server/server.py" \
  --langs "$LANGS" --srcs "$SRCS" \
  "${ASR_ARGS[@]}" \
  --xeng --omni --kokoro "${VOICE_ARGS[@]}" --edition "$EDITION" \
  --voices-dir "${VOICES_DIR:-$W/voices}" \
  --endpoint-ms 900 --max-utterance-s 12 \
  "${MT_ARGS[@]}" \
  --port 8790
