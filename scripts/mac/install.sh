#!/usr/bin/env bash
# Install the stack natively on an Apple Silicon Mac (no Docker: Docker on a
# Mac cannot reach the GPU). Everything goes under STACK_HOME
# (default ~/translation-open-stack-data): a Python virtualenv, then the
# models on the first `scripts/mac/run.sh`.
#
#   bash scripts/mac/install.sh
#
# Needs macOS 14+, Homebrew, ~25 GB free (the models ~12 GB, plus MADLAD's
# full-precision download while it is converted, deleted afterwards).
# What runs where: docs/user-guide.md, "Mac (Apple Silicon)".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
W="${STACK_HOME:-$HOME/translation-open-stack-data}"
[ "$(uname -s)" = Darwin ] && [ "$(uname -m)" = arm64 ] ||
  { echo "This is for Apple Silicon Macs (M1 or later). Other machines: docs/user-guide.md" >&2; exit 1; }
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh" >&2; exit 1; }
# Python 3.12: the pinned torch, CTranslate2 and MLX wheels all exist for it.
PY="$(command -v python3.12 || true)"
[ -n "$PY" ] || { echo "== brew install python@3.12"; brew install python@3.12; PY="$(brew --prefix python@3.12)/bin/python3.12"; }
command -v espeak-ng >/dev/null || { echo "== brew install espeak-ng (the last-resort voice)"; brew install espeak-ng; }
mkdir -p "$W"
if [ ! -x "$W/venv/bin/python" ]; then
  echo "== virtualenv: $W/venv"
  "$PY" -m venv "$W/venv"
fi
# shellcheck source=/dev/null
. "$W/venv/bin/activate"
pip -q install --upgrade pip
echo "== Python packages (pinned by constraints.txt and constraints-mac.txt; several minutes)"
bash "$ROOT/scripts/install-deps.sh"
python3 -c "import mlx.core, mlx_lm, mlx_whisper, faster_whisper, kokoro, piper; print('packages ok; Apple GPU:', mlx.core.default_device())"
echo "Installed. Start it with:  bash scripts/mac/run.sh"
