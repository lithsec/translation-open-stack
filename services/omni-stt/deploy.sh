#!/usr/bin/env bash
# Build omni-stt and deploy it to Cloud Run on an NVIDIA L4, scaled to zero.
#
#   export PROJECT=my-project            # required
#   ./deploy.sh secret                   # once: the STT_TOKEN secret (reads the token from stdin)
#   ./deploy.sh build                    # Cloud Build -> Artifact Registry
#   ./deploy.sh deploy                   # gcloud run deploy
#   ./deploy.sh build-local              # or: docker build + push from this machine (linux/amd64)
#
# Optional: REGION (us-east4: has Cloud Run L4 and, on a new project, the only
# GPU quota we found; us-central1 had none, 2026-10-17), REPO (Artifact Registry
# repository, omni-stt), SERVICE (omni-stt), TAG (default: the git commit),
# SECRET (omni-stt-token), MAX_STREAMS (4: connections one instance takes),
# ENDPOINT_MS (300), MAX_UTTERANCE_S (6.0), MIN_SPEECH_MS (400): endpointing,
# passed to the service by "deploy" (README, Endpointing).
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

: "${PROJECT:?set PROJECT to the Google Cloud project id}"
REGION="${REGION:-us-east4}"
REPO="${REPO:-omni-stt}"
SERVICE="${SERVICE:-omni-stt}"
SECRET="${SECRET:-omni-stt-token}"
MAX_STREAMS="${MAX_STREAMS:-4}"
ENDPOINT_MS="${ENDPOINT_MS:-300}"
MAX_UTTERANCE_S="${MAX_UTTERANCE_S:-6.0}"
MIN_SPEECH_MS="${MIN_SPEECH_MS:-400}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
TAG="${TAG:-$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)}"
# The image's registry may be in another region than the service (lithos-talk:
# us-central1 registry, us-east4 service, where the L4 quota is).
REPO_REGION="${REPO_REGION:-$REGION}"
IMAGE="$REPO_REGION-docker.pkg.dev/$PROJECT/$REPO/$SERVICE:$TAG"

stage() {
  # The build context: this service and only the stack files it imports, so
  # neither the eval audio nor .git is uploaded to Cloud Build.
  local dir
  dir="$(mktemp -d)"
  cp "$HERE/server.py" "$HERE/mic.html" "$HERE/Dockerfile" "$dir/"
  cp "$ROOT/server/audio_in.py" "$ROOT/server/stack_auth.py" "$ROOT/constraints.txt" "$dir/"
  mkdir "$dir/engines"
  cp "$ROOT/server/engines/"{__init__,base,common,omnilingual}.py "$dir/engines/"
  echo "$dir"
}

case "${1:-}" in
  secret)
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
    gcloud secrets add-iam-policy-binding "$SECRET" --project "$PROJECT" \
      --member "serviceAccount:$num-compute@developer.gserviceaccount.com" \
      --role roles/secretmanager.secretAccessor >/dev/null
    echo "secret $SECRET updated"
    ;;
  build)
    ctx="$(stage)"
    # 32 GB build machine: the model fetch loads the checkpoint in float32 on its CPU.
    # No --region: regional build pools refuse e2-highcpu-32 on a new project;
    # the global pool takes it.
    gcloud builds submit "$ctx" --tag "$IMAGE" --project "$PROJECT" \
      --machine-type e2-highcpu-32 --timeout 3600s
    rm -rf "$ctx"
    echo "built $IMAGE"
    ;;
  build-local)
    ctx="$(stage)"
    docker build --platform linux/amd64 -t "$IMAGE" "$ctx"
    rm -rf "$ctx"
    docker image ls "$IMAGE"
    gcloud auth configure-docker "$REPO_REGION-docker.pkg.dev" --quiet
    docker push "$IMAGE"
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
    gcloud run deploy "$SERVICE" --project "$PROJECT" --region "$REGION" --image "$IMAGE" \
      --gpu 1 --gpu-type nvidia-l4 --no-gpu-zonal-redundancy \
      --cpu 4 --memory 16Gi --no-cpu-throttling \
      --min-instances 0 --max-instances 1 \
      --concurrency "$MAX_STREAMS" --timeout 3600 --port 8080 \
      --set-env-vars "STT_MAX_CONNECTIONS=$MAX_STREAMS,ENDPOINT_MS=$ENDPOINT_MS,MAX_UTTERANCE_S=$MAX_UTTERANCE_S,MIN_SPEECH_MS=$MIN_SPEECH_MS" \
      --set-secrets "STT_TOKEN=$SECRET:latest" \
      --no-invoker-iam-check
    url="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
    echo "health: $url/health   mic test: $url/mic   stream: ${url/https:/wss:}/listen?langs=ht,en"
    ;;
  stage)
    stage
    ;;
  *)
    sed -n '2,23p' "$0"
    exit 2
    ;;
esac
