#!/usr/bin/env bash
# Build omni-stt and deploy it to Cloud Run on an NVIDIA L4, scaled to zero.
#
#   export PROJECT=my-project            # required
#   ./deploy.sh secret                   # once: the STT_TOKEN secret (reads the token from stdin;
#                                        # SECRET=<name> for another, e.g. the two below)
#   ./deploy.sh build                    # Cloud Build -> Artifact Registry
#   ./deploy.sh deploy                   # gcloud run deploy
#   ./deploy.sh build-local              # or: docker build + push from this machine (linux/amd64)
#   ./deploy.sh build-ft                 # a fine-tuned checkpoint layered on BASE_TAG (Dockerfile.ft)
#   ./deploy.sh build-voices             # the Haitian Creole voices layered on BASE_TAG (Dockerfile.voices)
#   ./deploy.sh 7b-build                 # Meta's stock omniASR_LLM_7B (bf16): images and bucket copy (7b/)
#   ./deploy.sh 7b-deploy                # the separate omni-stt-7b service (lo, km), /listen only
#
# 7b-build: converts Meta's omniASR_LLM_7B checkpoint to bf16 inside Cloud Build
# (7b/to_bf16.py), copies it to MODEL_BUCKET (gs://, private; for the volume
# and OMNI_FETCH options), and builds two images in the registry: <TAG>-7b-base
# (no checkpoint: 7b/Dockerfile.base) and <TAG>-7b (checkpoint baked in:
# 7b/Dockerfile.baked), pushed to REPO_REGION and to EXTRA_REPO_REGIONS. Stock
# weights only. 7b-deploy: SERVICE_7B (omni-stt-7b), STORAGE (baked|gcs|fetch: where
# the checkpoint comes from), MAX_STREAMS (6), MEMORY (32Gi), CPU (8).
#
# Optional: REGION (us-east4: has Cloud Run L4 and, on a new project, the only
# GPU quota we found; us-central1 had none, 2026-10-17), REPO (Artifact Registry
# repository, omni-stt), SERVICE (omni-stt), TAG (default: the git commit),
# SECRET (omni-stt-token), MAX_STREAMS (4: connections one instance takes),
# ENDPOINT_MS (300), MAX_UTTERANCE_S (6.0), MIN_SPEECH_MS (400): endpointing,
# passed to the service by "deploy" (README, Endpointing). OMNI_CARD (default
# omniASR_LLM_300M): the Omnilingual card the service loads. HT_VOICE (coqui):
# /speak's voice when a request names none (mms|coqui). EDITION (commercial):
# which voices /speak may use (server.py; commercial never loads MMS, which is
# CC-BY-NC; nonprofit offers it; both decides per signed token's "ed" claim, and
# a static STT_TOKEN carries none, so it gets commercial).
# SIGNING_SECRET, NONPROFIT_SECRET (unset: not mounted): Secret Manager secrets
# mounted as STT_SIGNING_KEY (signed tokens, e.g. Lithos Talk's, "ed" commercial)
# and STT_TOKEN_NONPROFIT (a static token served as non-profit, e.g. Live
# Translation's) beside STT_TOKEN (server.py, Credentials). Every deploy sets the
# service's whole secret list, so keep them set (private.env) once they exist,
# or a redeploy drops them and the clients that use them are refused. DEPLOY_FLAGS: extra
# gcloud run deploy flags, e.g. "--no-traffic --tag ft" to test a revision first.
# BATCH_MAX (8), BATCH_WAIT_MS (10): the GPU micro-batcher (STT_BATCH_MAX,
# STT_BATCH_WAIT_MS); MAX_SPEAKERS (4): open /speak sockets (STT_MAX_SPEAKERS).
#
# build-ft: FT_CARD and FT_WEIGHTS (both required: the card's name, and a PRIVATE
# gs:// folder holding <FT_CARD>.pt and SHA256SUMS), BASE_TAG (the omni-stt image
# tag to layer on), TAG (default: <BASE_TAG>-<FT_CARD>). The weights go from the
# bucket into the image inside Cloud Build. Then deploy with TAG=<that tag>
# OMNI_CARD=<FT_CARD>; OMNI_CARD=omniASR_LLM_300M on the same image serves the
# base model again.
#
# build-voices: BASE_TAG (required; the omni-stt image tag to layer on), TAG
# (default: <BASE_TAG>-voices). Built in Cloud Build from the staged context;
# the base image (and any fine-tuned weights in it) never leaves the registry.
#
# Private settings (a fine-tuned card's name, its bucket, your project and
# registry) live in private.env beside this script, which git ignores (copy
# private.env.example). It holds KEY=value lines only; it is read, not run, and
# a variable already in the environment wins. PRIVATE_ENV names another file.
#
# The private-registry guard: build-ft and build-voices (whose base may carry
# fine-tuned weights) refuse unless the image is an Artifact Registry
# (<region>-docker.pkg.dev) one, and refuse anything naming ghcr.io, docker.io
# or another public registry. DRY_RUN=1 prints the gcloud/docker commands
# instead of running them (tests/test_omni_stt_deploy.py).
#
# Before the first deploy, once per project (not done by this script):
#   gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
#       cloudbuild.googleapis.com secretmanager.googleapis.com --project "$PROJECT"
#   gcloud artifacts repositories create "$REPO" --repository-format docker \
#       --location "$REGION" --project "$PROJECT"
#   Cloud Run GPU quota for nvidia-l4 in $REGION (IAM & Admin > Quotas: "Total Nvidia
#   L4 GPU allocation without zonal redundancy, per project per region"); new
#   projects have 0 or a small grant.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"

# private.env: KEY=value lines, never executed; the environment wins.
PRIVATE_ENV="${PRIVATE_ENV:-$HERE/private.env}"
if [ -f "$PRIVATE_ENV" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || { echo "private.env: ignoring a line that is not KEY=value" >&2; continue; }
    val="${val#\"}"; val="${val%\"}"; val="${val#\'}"; val="${val%\'}"
    [ -n "${!key+x}" ] || export "$key=$val"
  done < "$PRIVATE_ENV"
fi

# DRY_RUN=1: print what would run (gcloud, docker), run nothing.
run() {
  if [ "${DRY_RUN:-0}" = 1 ]; then
    printf '+'; printf ' %q' "$@"; printf '\n'
  else
    "$@"
  fi
}

# Fine-tuned weights may be derived from licensed content: an image that
# carries them (or may: build-voices layers on any base) only goes to a
# private Artifact Registry repository, never a public registry.
require_private_registry() {
  local what="$1"
  case "$IMAGE$PROJECT$REPO" in
    *ghcr.io*|*docker.io*|*quay.io*|*gcr.io/*|*public.ecr.aws*)
      echo "refusing $what: $IMAGE names a public registry; fine-tuned images stay in a private Artifact Registry repository" >&2
      exit 3 ;;
  esac
  if ! [[ "$IMAGE" =~ ^[a-z0-9-]+-docker\.pkg\.dev/[a-z0-9-]+/[a-z0-9._-]+/[a-z0-9._-]+:[A-Za-z0-9._-]+$ ]]; then
    echo "refusing $what: $IMAGE is not an Artifact Registry image (<region>-docker.pkg.dev/<project>/<repo>/<name>:<tag>)" >&2
    exit 3
  fi
}

: "${PROJECT:?set PROJECT to the Google Cloud project id}"
REGION="${REGION:-us-east4}"
REPO="${REPO:-omni-stt}"
SERVICE="${SERVICE:-omni-stt}"
SECRET="${SECRET:-omni-stt-token}"
SIGNING_SECRET="${SIGNING_SECRET:-}"
NONPROFIT_SECRET="${NONPROFIT_SECRET:-}"
SECRETS="STT_TOKEN=$SECRET:latest"
for pair in "STT_SIGNING_KEY=$SIGNING_SECRET" "STT_TOKEN_NONPROFIT=$NONPROFIT_SECRET"; do
  name="${pair#*=}"
  [ -z "$name" ] && continue
  [[ "$name" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "refusing: ${pair%%=*}'s secret name must be a plain Secret Manager name" >&2; exit 3; }
  [ "$name" != "$SECRET" ] || { echo "refusing: ${pair%%=*} cannot use the STT_TOKEN secret ($SECRET)" >&2; exit 3; }
  SECRETS="$SECRETS,${pair%%=*}=$name:latest"
done
MAX_STREAMS="${MAX_STREAMS:-4}"
ENDPOINT_MS="${ENDPOINT_MS:-300}"
MAX_UTTERANCE_S="${MAX_UTTERANCE_S:-6.0}"
MIN_SPEECH_MS="${MIN_SPEECH_MS:-400}"
OMNI_CARD="${OMNI_CARD:-omniASR_LLM_300M}"
HT_VOICE="${HT_VOICE:-coqui}"
EDITION="${EDITION:-commercial}"
BATCH_MAX="${BATCH_MAX:-8}"
BATCH_WAIT_MS="${BATCH_WAIT_MS:-10}"
MAX_SPEAKERS="${MAX_SPEAKERS:-4}"
if [ "${1:-}" = build-ft ]; then
  : "${FT_CARD:?set FT_CARD to the fine-tuned card name (private.env)}"
  : "${FT_WEIGHTS:?set FT_WEIGHTS to the private gs:// folder with the checkpoint (private.env)}"
  : "${BASE_TAG:?set BASE_TAG to the omni-stt image tag to layer the weights on}"
  TAG="${TAG:-$BASE_TAG-$FT_CARD}"
fi
if [ "${1:-}" = build-voices ]; then
  : "${BASE_TAG:?set BASE_TAG to the omni-stt image tag to layer the voices on}"
  TAG="${TAG:-$BASE_TAG-voices}"
fi
TAG="${TAG:-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)}"
# The image's registry may be in another region than the service (e.g. a
# us-central1 registry for a us-east4 service, where the L4 quota is).
REPO_REGION="${REPO_REGION:-$REGION}"
IMAGE="$REPO_REGION-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:$TAG"

stage() {
  # The build context: this service and only the stack files it imports, so
  # neither the eval audio nor .git is uploaded to Cloud Build.
  local dir
  dir="$(mktemp -d)"
  cp "$HERE/server.py" "$HERE/omni_batch.py" "$HERE/voices.py" "$HERE/ht_numbers.py" "$HERE/mic.html" "$HERE/Dockerfile" "$dir/"
  cp "$ROOT/server/audio_in.py" "$ROOT/server/stack_auth.py" "$ROOT/server/licences.py" "$ROOT/constraints.txt" "$dir/"
  mkdir "$dir/engines"
  cp "$ROOT/server/engines/"{__init__,base,common,omnilingual,mms,coqui}.py "$dir/engines/"
  echo "$dir"
}

case "${1:-}" in
  secret)
    [ "${DRY_RUN:-0}" != 1 ] || { echo "+ (secret: reads the token from stdin; nothing done in a dry run)"; exit 0; }
    # The token comes from stdin so it never lands in shell history or argv:
    #   openssl rand -hex 32 | ./deploy.sh secret
    if gcloud secrets describe "$SECRET" --project "$PROJECT" >/dev/null 2>&1; then
      tr -d '\r\n' | gcloud secrets versions add "$SECRET" --data-file=- --project "$PROJECT"
    else
      tr -d '\r\n' | gcloud secrets create "$SECRET" --data-file=- --replication-policy automatic --project "$PROJECT"
    fi
    # The service's runtime identity (the default compute service account
    # unless you deploy with --service-account) must be able to read it.
    num="$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')"
    run gcloud secrets add-iam-policy-binding "$SECRET" --project "$PROJECT" \
      --member "serviceAccount:$num-compute@developer.gserviceaccount.com" \
      --role roles/secretmanager.secretAccessor >/dev/null
    echo "secret $SECRET updated"
    ;;
  build)
    ctx="$(stage)"
    # 32 GB build machine: the model fetch loads the checkpoint in float32 on its CPU.
    # No --region: regional build pools refuse e2-highcpu-32 on a new project;
    # the global pool takes it.
    run gcloud builds submit "$ctx" --tag "$IMAGE" --project "$PROJECT" \
      --machine-type e2-highcpu-32 --timeout 3600s
    rm -rf "$ctx"
    echo "built $IMAGE"
    ;;
  build-ft)
    require_private_registry build-ft
    case "$FT_WEIGHTS" in
      gs://*) ;;
      *) echo "refusing build-ft: FT_WEIGHTS must be a gs:// folder (got a non-gs:// value)" >&2; exit 3 ;;
    esac
    [[ "$FT_CARD" =~ ^[A-Za-z0-9._-]+$ ]] || { echo "refusing build-ft: FT_CARD must be a plain card name" >&2; exit 3; }
    base="$REPO_REGION-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:$BASE_TAG"
    ctx="$(mktemp -d)"
    cp "$HERE/Dockerfile.ft" "$ctx/Dockerfile"
    # The weights never touch this machine: Cloud Build copies them from the
    # bucket into its workspace, checks them (Dockerfile.ft) and bakes them in.
    cat > "$ctx/cloudbuild.yaml" <<YAML
steps:
- name: gcr.io/google.com/cloudsdktool/cloud-sdk:slim
  entrypoint: bash
  args: ["-c", "mkdir -p ft && gcloud storage cp '${FT_WEIGHTS%/}/$FT_CARD.pt' '${FT_WEIGHTS%/}/SHA256SUMS' ft/ && ls -l ft"]
- name: gcr.io/cloud-builders/docker
  args: ["build", "--build-arg", "BASE_IMAGE=$base", "--build-arg", "FT_CARD=$FT_CARD", "-t", "$IMAGE", "."]
images: ["$IMAGE"]
options:
  machineType: E2_HIGHCPU_8
  diskSizeGb: 100
timeout: 3600s
YAML
    run gcloud builds submit "$ctx" --config "$ctx/cloudbuild.yaml" --project "$PROJECT"
    rm -rf "$ctx"
    echo "built $IMAGE (deploy with TAG=$TAG OMNI_CARD=$FT_CARD)"
    ;;
  build-voices)
    require_private_registry build-voices
    base="$REPO_REGION-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:$BASE_TAG"
    ctx="$(stage)"
    cp "$HERE/Dockerfile.voices" "$ctx/Dockerfile"
    cat > "$ctx/cloudbuild.yaml" <<YAML
steps:
- name: gcr.io/cloud-builders/docker
  args: ["build", "--build-arg", "BASE_IMAGE=$base", "-t", "$IMAGE", "."]
images: ["$IMAGE"]
options:
  machineType: E2_HIGHCPU_8
  diskSizeGb: 100
timeout: 3600s
YAML
    run gcloud builds submit "$ctx" --config "$ctx/cloudbuild.yaml" --project "$PROJECT"
    rm -rf "$ctx"
    echo "built $IMAGE (deploy with TAG=$TAG, and the base's OMNI_CARD)"
    ;;
  build-local)
    ctx="$(stage)"
    run docker build --platform linux/amd64 -t "$IMAGE" "$ctx"
    rm -rf "$ctx"
    run docker image ls "$IMAGE"
    run gcloud auth configure-docker "$REPO_REGION-docker.pkg.dev" --quiet
    run docker push "$IMAGE"
    ;;
  deploy)
    # GPU services need at least 4 CPUs and 16 GiB. Always-allocated CPU
    # (--no-cpu-throttling) is required with a GPU, and keeps the VAD running
    # between messages. --timeout 3600 is Cloud Run's ceiling: a WebSocket ends
    # after an hour and the client reconnects (README). Concurrency matches the
    # server's own limit: one model serves every stream on the instance, and
    # more than a few real-time streams would queue behind it.
    # --no-invoker-iam-check: the service checks its tokens itself, because a
    # browser (the /mic page) cannot attach a Google identity token to a WebSocket.
    # (--allow-unauthenticated grants allUsers, which an organisation's domain-
    # restricted-sharing policy refuses; this skips the check without that grant.)
    # --no-gpu-zonal-redundancy: cheaper and needs the smaller quota; a zone
    # outage means a failed cold start, which a reconnecting client retries.
    run gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --image "$IMAGE" \
      --gpu 1 --gpu-type nvidia-l4 --no-gpu-zonal-redundancy \
      --cpu 4 --memory 16Gi --no-cpu-throttling \
      --min-instances 0 --max-instances 1 \
      --concurrency "$MAX_STREAMS" --timeout 3600 --port 8080 \
      --set-env-vars "STT_MAX_CONNECTIONS=$MAX_STREAMS,ENDPOINT_MS=$ENDPOINT_MS,MAX_UTTERANCE_S=$MAX_UTTERANCE_S,MIN_SPEECH_MS=$MIN_SPEECH_MS,OMNI_CARD=$OMNI_CARD,HT_VOICE=$HT_VOICE,EDITION=$EDITION,STT_MAX_SPEAKERS=$MAX_SPEAKERS,STT_BATCH_MAX=$BATCH_MAX,STT_BATCH_WAIT_MS=$BATCH_WAIT_MS" \
      --set-secrets "$SECRETS" \
      --no-invoker-iam-check ${DEPLOY_FLAGS:-}
    [ "${DRY_RUN:-0}" != 1 ] || exit 0
    url="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
    echo "health: $url/health   mic test: $url/mic   stream: ${url/https:/wss:}/listen?langs=ht,en   voices: ${url/https:/wss:}/speak"
    ;;
  7b-build)
    : "${MODEL_BUCKET:?set MODEL_BUCKET (gs://..., private) for the 7B checkpoint copy}"
    ctx="$(stage)"
    cp "$HERE/7b/"* "$ctx/"
    printf '*.pt\nckpt/\n' > "$ctx/.dockerignore"
    base="$REPO_REGION-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:$TAG-7b-base"
    baked="$REPO_REGION-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:$TAG-7b"
    tags_base="\"-t\", \"$base\""; tags_baked="\"-t\", \"$baked\""; imgs="\"$base\", \"$baked\""
    for r in ${EXTRA_REPO_REGIONS:-}; do
      tags_base="$tags_base, \"-t\", \"$r-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:$TAG-7b-base\""
      tags_baked="$tags_baked, \"-t\", \"$r-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:$TAG-7b\""
      imgs="$imgs, \"$r-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:$TAG-7b-base\", \"$r-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:$TAG-7b\""
    done
    cat > "$ctx/cloudbuild.yaml" <<YAML
steps:
- id: ckpt
  name: python:3.12-slim-bookworm
  entrypoint: bash
  args:
  - -c
  - |
    set -e
    apt-get update -qq && apt-get install -y -qq curl >/dev/null
    pip install -q --index-url https://download.pytorch.org/whl/cpu torch==2.8.0 numpy
    mkdir -p ckpt && cd ckpt
    t=\$\$(date +%s)
    curl -sSfL --retry 5 -o fp32.pt https://dl.fbaipublicfiles.com/mms/omniASR-LLM-7B.pt
    echo "downloaded \$\$(du -h fp32.pt | cut -f1) in \$\$((\$\$(date +%s) - t))s"
    python ../to_bf16.py fp32.pt omniASR_LLM_7B_bf16.pt
    rm fp32.pt
    sha256sum omniASR_LLM_7B_bf16.pt > SHA256SUMS && cat SHA256SUMS && ls -l
    cp ../Dockerfile.baked Dockerfile
- id: upload
  waitFor: [ckpt]
  name: gcr.io/google.com/cloudsdktool/cloud-sdk:slim
  args: ["gcloud", "storage", "cp", "ckpt/omniASR_LLM_7B_bf16.pt", "ckpt/SHA256SUMS", "${MODEL_BUCKET%/}/omniASR_LLM_7B_bf16/"]
- id: base
  waitFor: ["-"]
  name: gcr.io/cloud-builders/docker
  args: ["build", "-f", "Dockerfile.base", $tags_base, "."]
- id: baked
  waitFor: [ckpt, base]
  name: gcr.io/cloud-builders/docker
  dir: ckpt
  args: ["build", "--build-arg", "BASE_IMAGE=$base", $tags_baked, "."]
images: [$imgs]
options:
  machineType: E2_HIGHCPU_32
  diskSizeGb: 300
timeout: 7200s
YAML
    [ "${DRY_RUN:-0}" != 1 ] || cat "$ctx/cloudbuild.yaml"
    run gcloud builds submit "$ctx" --config "$ctx/cloudbuild.yaml" --project "$PROJECT"
    rm -rf "$ctx"
    echo "built $base and $baked; checkpoint at ${MODEL_BUCKET%/}/omniASR_LLM_7B_bf16/"
    ;;
  7b-deploy)
    # Meta's stock 7B for Lao and Khmer, beside omni-stt (whose 300M card stays
    # for ht and the rest). /listen only: no voices. STORAGE picks where the
    # checkpoint is read from at a cold start:
    #   baked  the image <TAG>-7b (the checkpoint in its last layer)
    #   gcs    the image <TAG>-7b-base + a Cloud Storage volume at /mnt/models
    #   fetch  the image <TAG>-7b-base + a parallel copy into /tmp (memory) at start
    STORAGE="${STORAGE:-baked}"
    MAX_STREAMS="${MAX_STREAMS_7B:-6}"
    extra=()
    envs="STT_SERVE=listen,STT_MAX_CONNECTIONS=$MAX_STREAMS,ENDPOINT_MS=$ENDPOINT_MS,MAX_UTTERANCE_S=$MAX_UTTERANCE_S,MIN_SPEECH_MS=$MIN_SPEECH_MS,STT_BATCH_MAX=$BATCH_MAX,STT_BATCH_WAIT_MS=$BATCH_WAIT_MS,OMNI_MMAP=${OMNI_MMAP:-1}${EXTRA_ENV:+,$EXTRA_ENV}"
    case "$STORAGE" in
      baked) IMAGE="$REPO_REGION-docker.pkg.dev/$PROJECT/$REPO/omni-stt:$TAG-7b"; envs="$envs,OMNI_CARD=omniASR_LLM_7B_bf16" ;;
      gcs)   IMAGE="$REPO_REGION-docker.pkg.dev/$PROJECT/$REPO/omni-stt:$TAG-7b-base"; envs="$envs,OMNI_CARD=omniASR_LLM_7B_bf16_volume"
             : "${MODEL_BUCKET:?set MODEL_BUCKET}"
             b="${MODEL_BUCKET#gs://}"; b="${b%/}"
             extra+=(--add-volume "name=models,type=cloud-storage,bucket=$b,readonly=true,mount-options=only-dir=omniASR_LLM_7B_bf16${GCS_MOUNT_OPTIONS:+;$GCS_MOUNT_OPTIONS}"
                     --add-volume-mount "volume=models,mount-path=/mnt/models") ;;
      fetch) IMAGE="$REPO_REGION-docker.pkg.dev/$PROJECT/$REPO/omni-stt:$TAG-7b-base"
             : "${MODEL_BUCKET:?set MODEL_BUCKET}"
             envs="$envs,OMNI_CARD=omniASR_LLM_7B_bf16_tmp,OMNI_FETCH=${MODEL_BUCKET%/}/omniASR_LLM_7B_bf16/omniASR_LLM_7B_bf16.pt,OMNI_FETCH_TO=/tmp/models/omniASR_LLM_7B_bf16.pt" ;;
      *) echo "STORAGE must be baked, gcs or fetch" >&2; exit 2 ;;
    esac
    # (--no-gpu-zonal-redundancy, --no-invoker-iam-check: as "deploy" says.)
    # The startup probe: a TCP check on the port, which opens only once the
    # model is loaded and warm. Every 2 s (at 10 s a ready instance waited up
    # to 10 s more for its first request), up to 15 min before Cloud Run gives
    # up (a cold start from the volume took 6 min).
    run gcloud run deploy "${SERVICE_7B:-omni-stt-7b}" --project "$PROJECT" --region "$REGION" --image "$IMAGE" \
      --gpu 1 --gpu-type nvidia-l4 --no-gpu-zonal-redundancy \
      --cpu "${CPU:-8}" --memory "${MEMORY:-32Gi}" --no-cpu-throttling --cpu-boost \
      --min-instances 0 --max-instances 1 \
      --concurrency "$MAX_STREAMS" --timeout 3600 --port 8080 \
      --startup-probe "tcpSocket.port=8080,initialDelaySeconds=0,periodSeconds=2,timeoutSeconds=2,failureThreshold=450" \
      --set-env-vars "$envs" \
      --set-secrets "STT_TOKEN=$SECRET:latest" \
      --no-invoker-iam-check ${extra[@]+"${extra[@]}"} ${DEPLOY_FLAGS:-}
    ;;
  stage)
    stage
    ;;
  *)
    sed -n '2,/^set -euo/p' "$0" | sed '$d'
    exit 2
    ;;
esac
