# omni-stt for Cloud Run with a GPU (NVIDIA L4): Omnilingual ASR, VoxLingua107
# language ID and Silero VAD, with every model inside the image.
#
# Build context: the directory deploy.sh stages (this folder plus the stack files
# it reuses: server/audio_in.py, stack_auth.py, engines/, constraints.txt).
#   ./deploy.sh build-local      # docker build here
#   ./deploy.sh build            # Cloud Build
#
# Size: ~12 GB unpacked (~7-8 GB compressed): PyTorch with its CUDA 12.8 libraries
# ~5 GB, Omnilingual's 300M LLM checkpoint 6.1 GB (fp32 on disk), the rest small.
#
# Models are baked in, not fetched at start: a scale-to-zero service pays its cold
# start on every first caller, and a 6 GB download from Meta's CDN would be most of it.
#
# Base: plain Python 3.12, not a CUDA image. PyPI's torch 2.8.0 for Linux is the
# CUDA 12.8 build and brings its own CUDA libraries as nvidia-* wheels; Cloud Run
# supplies the driver. Pinned by digest (a tag can be re-pushed). To move it:
# docker buildx imagetools inspect python:3.12-slim-bookworm, take "Digest:".
# (digest read 2026-10-17)
ARG BASE_IMAGE=python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libsndfile: fairseq2's audio decoding. The compiler, cmake and Boost: kenlm
# (pulled by Omnilingual) has no wheel and compiles from source (the stack's
# docs/dev/lessons-learned.md; the first Cloud Build failed on it).
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 ca-certificates \
      build-essential cmake libboost-program-options-dev libboost-system-dev libboost-thread-dev \
      libboost-test-dev zlib1g-dev libbz2-dev liblzma-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/stt

# Every version from the stack's lock (constraints.txt: the pins Omnilingual was
# verified on, numpy 1.26.4 and scipy 1.13.1 for fairseq2, torchaudio == torch).
# One pip call, as install-deps.sh's Omnilingual step does, so fairseq2 cannot
# repin torch out from under torchaudio.
COPY constraints.txt ./
RUN pip install -c constraints.txt torch==2.8.0 torchaudio==2.8.0 \
 && pip install -c constraints.txt omnilingual-asr torchaudio==2.8.0 scipy==1.13.1 \
      speechbrain websockets huggingface_hub \
 && python -c "import torch, omnilingual_asr, speechbrain, websockets; print('torch', torch.__version__, 'cuda', torch.version.cuda)"

# Where the models live, at build time and at run time alike.
ENV STT_MODELS=/opt/models \
    HF_HOME=/opt/models/hf \
    TORCH_HOME=/opt/models/torch \
    FAIRSEQ2_CACHE_DIR=/opt/models/fairseq2 \
    OMNI_CARD=omniASR_LLM_300M

# An unprivileged user, made before the models land: the caches must be its
# own (SpeechBrain re-links its savedir at load), and a chown afterwards would
# copy 6 GB into another layer.
RUN useradd --uid 10001 --create-home stt && mkdir -p /opt/models && chown stt /opt/models
COPY . ./
USER stt
# Load each model once, by the server's own code, so the cache paths are the
# ones it will read. CPU only: the build machine has no GPU (deploy.sh asks
# Cloud Build for a 32 GB machine: the checkpoint loads in float32 on a CPU).
RUN python server.py --fetch && du -sh /opt/models/*

# Run time: offline. A missing model fails at start instead of downloading.
ENV HF_HUB_OFFLINE=1 \
    PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
