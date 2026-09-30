# The stack as one image: every package installed and checked at build time,
# models kept OUT (they go on the /workspace volume, filled on first start).
#
#   docker build -t lithos-stack .
#   docker compose up -d        # from the repository root: see README "Quick start"
#
# Three of this project's worst days were environment, not code: Omnilingual
# silently missing so Khmer served confident nonsense; transformers pinned at
# 4.46.3 while the CT2 converter needs >=4.55; fairseq2 downgrading numpy and
# stranding scipy. The packages come from scripts/install-deps.sh, the same script a
# RunPod pod runs, so the image and the pods can't drift apart.
#
# Base: the exact image the RunPod pods run (torch 2.8, CUDA 12.8.1, Ubuntu
# 24.04). CUDA 12.8 is what Blackwell (sm_120) needs and runs fine on older
# cards. Keeping it also means this image can replace the stock one on RunPod:
# scripts/runpod/runpod-start.sh sees the packages and skips its ~3 min of installs, and the
# pod's own start command (which replaces CMD) still runs /start.sh for ssh.
# Do not float this tag: the CUDA/torch/CTranslate2 triple is the part most
# likely to break silently on someone else's GPU. Pinned by digest as well (a
# tag can be re-pushed): the multi-arch index of
#   runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404   (pushed 2025-10-09)
# To move it: docker buildx imagetools inspect <tag>, and take "Digest:".
ARG BASE_IMAGE=runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404@sha256:0a360022e8de4375af99430f84e8b38951acc397252163a37ceac7204d01be35
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="Translation Open Stack" \
      org.opencontainers.image.description="Self-hosted live speech translation: recognition, translation and voices on one GPU. No model weights inside; they download to /workspace on first start." \
      org.opencontainers.image.source="https://github.com/lithsec/translation-open-stack" \
      org.opencontainers.image.licenses="Apache-2.0 AND GPL-3.0-or-later"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1

# espeak-ng: phonemiser fallback for Piper/Kokoro. lsof: scripts/run.sh's "port already
# in use" check. iproute2 (ss) + curl: the RunPod idle stop and health checks.
RUN apt-get update && apt-get install -y --no-install-recommends \
      espeak-ng lsof iproute2 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The base's torch is the one everything below is pinned against; stop here if
# the tag ever changes underneath us.
RUN python3 -c "import torch; v = torch.__version__; print('torch', v, 'cuda', torch.version.cuda); \
assert v.startswith('2.8.'), v"

WORKDIR /opt/stack

# Python packages: one layer, the pods' own script. STRICT: a missing optional
# extra fails the build instead of degrading a language at runtime.
# constraints.txt pins every version (see its header).
COPY constraints.txt constraints-voxcpm.txt ./
COPY scripts/install-deps.sh scripts/
RUN STRICT=1 bash scripts/install-deps.sh && rm -rf /root/.cache

# VoxCPM2's own virtualenv (it pins library versions the stack must not
# inherit), baked in; its weights still go on the volume.
ENV VOXCPM_VENV=/opt/venv_voxcpm
COPY scripts/prepare-voices.sh scripts/
RUN VOXCPM_VENV_ONLY=1 bash scripts/prepare-voices.sh && rm -rf /root/.cache \
 && /opt/venv_voxcpm/bin/python -c "import voxcpm, soundfile; print('voxcpm ok')"

# Fail the BUILD if anything the server needs is missing, rather than at the
# moment someone starts speaking. Every import listed has broken this stack at
# least once.
RUN python3 -c "\
import importlib.util; \
need=['torch','torchaudio','transformers','faster_whisper','ctranslate2','onnxruntime',\
'speechbrain','kokoro','misaki','omnilingual_asr','piper','numpy','scipy','websockets','pyopenjtalk','TTS',\
'accelerate','bitsandbytes','sentencepiece','unidic']; \
missing=[m for m in need if not importlib.util.find_spec(m)]; \
exit('MISSING: '+', '.join(missing)) if missing else print('all runtime imports present')" \
 && python3 -c "import spacy; spacy.load('en_core_web_sm'); print('spacy model ok')" \
 && python3 -c "import transformers; assert transformers.__version__.startswith('4.'), transformers.__version__" \
 && command -v ct2-transformers-converter

# GPL-3.0 programs ship in this image (espeak-ng, piper-tts, phonemizer-fork):
# their licence and complete source go in with them, /opt/stack/licences/.
COPY scripts/collect-gpl-source.sh scripts/
RUN bash scripts/collect-gpl-source.sh /opt/stack/licences

# The stack itself (.dockerignore keeps local voices and caches out).
COPY . ./
RUN chmod +x scripts/*.sh scripts/runpod/*.sh

# An unprivileged user for the Docker / compose path (docker-compose.yml runs
# the stack as it). The image's default user stays root ON PURPOSE: RunPod's
# start command replaces CMD and must exec /start.sh, whose sshd needs root, and
# RunPod mounts its network volume at /workspace owned by root. Everything the
# stack writes at run time goes to /workspace (models, caches, logs) or $HOME.
RUN groupadd --gid 10001 stack \
 && useradd --uid 10001 --gid stack --create-home --home-dir /home/stack --shell /bin/bash stack \
 && mkdir -p /workspace && chown stack:stack /workspace

# Models, voices and caches: the volume. HF_HOME matches the pods'.
ENV HF_HOME=/workspace/hf-cache
VOLUME /workspace
EXPOSE 8790

# CMD, not ENTRYPOINT: RunPod replaces CMD with the pod's start command.
CMD ["/opt/stack/scripts/docker-entrypoint.sh"]
