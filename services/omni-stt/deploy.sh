#!/usr/bin/env bash
# Build omni-stt and deploy it to Cloud Run on an NVIDIA L4, scaled to zero.
#
#   export PROJECT=my-project            # required
#   ./deploy.sh secret                   # once: the STT_TOKEN secret (reads the token from stdin)
#   ./deploy.sh build                    # Cloud Build -> Artifact Registry
#   ./deploy.sh deploy                   # gcloud run deploy
#   ./deploy.sh build-local              # or: docker build + push from this machine (linux/amd64)
#   ./deploy.sh build-ft                 # a fine-tuned checkpoint layered on BASE_TAG (Dockerfile.ft)
#   ./deploy.sh build-voices             # the Haitian Creole voices layered on BASE_TAG (Dockerfile.voices)
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
# a static STT_TOKEN carries none, so it gets commercial). DEPLOY_FLAGS: extra
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
    # --no-invoker-iam-check: the service checks STT_TOKEN itself, because a
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
      --set-secrets "STT_TOKEN=$SECRET:latest" \
      --no-invoker-iam-check ${DEPLOY_FLAGS:-}
    [ "${DRY_RUN:-0}" != 1 ] || exit 0
    url="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
    echo "health: $url/health   mic test: $url/mic   stream: ${url/https:/wss:}/listen?langs=ht,en   voices: ${url/https:/wss:}/speak"
    ;;
  stage)
    stage
    ;;
  *)
    sed -n '2,/^set -euo/p' "$0" | sed '$d'
    exit 2
    ;;
esac
