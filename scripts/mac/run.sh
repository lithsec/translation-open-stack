#!/usr/bin/env bash
# Start the stack on an Apple Silicon Mac, after scripts/mac/install.sh. The
# first start downloads and converts the models (~12 GB kept; 20-40 minutes);
# later starts take a minute or two.
#
#   STACK_TOKEN=$(openssl rand -hex 32) bash scripts/mac/run.sh
#
# Then connect apps to ws://<this Mac's address>:8790 with that token (on the
# same network; for anything further, put TLS in front, as for any install).
# STACK_PROFILE picks the setup (default: mac, profiles/mac.toml, which notes
# the changes for 8 GB and 32 GB Macs). LANGS / SRCS / EDITION work as everywhere else.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export STACK_HOME="${STACK_HOME:-$HOME/translation-open-stack-data}"
[ -x "$STACK_HOME/venv/bin/python" ] || { echo "Run scripts/mac/install.sh first" >&2; exit 1; }
# shellcheck source=/dev/null
. "$STACK_HOME/venv/bin/activate"
export STACK_PROFILE="${STACK_PROFILE:-mac}"
# shellcheck source=../profile-env.sh
. "$ROOT/scripts/profile-env.sh"
export HF_HOME="${HF_HOME:-$STACK_HOME/hf-cache}"
export TORCH_HOME="${TORCH_HOME:-$STACK_HOME/torch-cache}"
export MT_SCRATCH="${MT_SCRATCH:-$STACK_HOME/.mt-build}"
# Operations MPS lacks fall back to the CPU instead of failing (Kokoro, MMS).
export PYTORCH_ENABLE_MPS_FALLBACK=1
if [ -z "${STACK_TOKEN:-}" ] && [ -z "${STACK_SIGNING_KEY:-}" ] && [ "${STACK_OPEN:-0}" != 1 ]; then
  echo "Set STACK_TOKEN (e.g. STACK_TOKEN=\$(openssl rand -hex 32)) so only your apps can connect," >&2
  echo "or STACK_OPEN=1 to run with no credential on a network where you trust every device." >&2
  exit 1
fi
LANGS="${LANGS:-en,es,fr,pt,de,ru,uk,zh,ja,km,lo,ht,ar,hi,vi,ko,tl,fa,id,tr,bn,ur,it,sw,ro}"
SRCS="${SRCS:-$LANGS}"
VOICES_DIR="$STACK_HOME/voices" bash "$ROOT/scripts/fetch-voices.sh" "$LANGS"
bash "$ROOT/scripts/prepare-mt.sh"
exec bash "$ROOT/scripts/run.sh" "$LANGS" "$SRCS"
