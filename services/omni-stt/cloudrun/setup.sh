#!/usr/bin/env bash
# Guided setup: the Omnilingual hearing services (omni-stt, and the 7B service
# for Lao and Khmer if you want it) on Cloud Run with an NVIDIA L4, scaled to
# zero, in your own Google Cloud project. Made for Cloud Shell (the "Open in
# Cloud Shell" button in services/omni-stt/README.md), and fine anywhere gcloud
# is signed in.
#
#   bash services/omni-stt/cloudrun/setup.sh              # asks what it needs
#   bash services/omni-stt/cloudrun/setup.sh --new-token  # also replace the access token
#
# Safe to run again: everything it makes is looked up first and reused, a
# finished image is not rebuilt, and a redeploy changes nothing that works.
# Answers can come from the environment instead of prompts:
#   PROJECT, REGION, WITH_7B (yes|no), NONPROFIT (yes|no), ASSUME_YES=1.
# OMNI_STT_IMAGE=build builds omni-stt in your project instead of pulling the
# published image (images.env).
# DRY_RUN=1 prints the commands that would change anything and runs only the
# read-only ones (tests/test_omni_stt_cloudrun.py).
#
# What it does, in order:
#   1. checks gcloud is signed in, the project exists and has billing;
#   2. asks for a region that offers Cloud Run L4 GPUs, and shows the plan;
#   3. enables the APIs (Cloud Run, Artifact Registry, Secret Manager, IAM,
#      Cloud Quotas, and Cloud Build when an image is built here), and checks
#      the L4 quota in the region when it can, before anything is built;
#   4. makes a service account for the services, and an access token in Secret
#      Manager that only that account can read (a token an unfinished run never
#      showed is replaced on the next run); when anything is built here, gives
#      Cloud Build's service account its role (new projects give it none);
#   5. gets the omni-stt image: from GitHub Container Registry through an
#      Artifact Registry remote repository, by pinned digest (images.env), or,
#      with OMNI_STT_IMAGE=build or no pin, built with Cloud Build here;
#   6. deploys omni-stt: 1 L4, min 0 / max 1 instances, CPU always allocated,
#      one hour request timeout (the WebSocket ceiling), concurrency = the rooms
#      one instance takes (4); a first deploy that outlasts gcloud's readiness
#      wait (the image copy) is waited out, not reported as a failure;
#   7. with the 7B: shows omni-stt's settings and token, then builds the 7B in
#      your project (images.env says why) and deploys it (concurrency 6);
#      then prints what to paste into Live Translation, the token shown once.
#
# Cost (public list prices, check https://cloud.google.com/run/pricing): about
# $1 an hour per service while an instance is up (the L4, 4 vCPU, 16 GiB), $0
# when idle (images: Artifact Registry storage, $0.10 per GB a month). A build
# in your project bills Cloud Build minutes once.
# teardown.sh removes everything this script makes.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SVC_DIR="$(cd "$HERE/.." && pwd)"
ROOT="$(cd "$SVC_DIR/../.." && pwd)"

SERVICE=omni-stt
SERVICE_7B=omni-stt-7b
SECRET_NAME=omni-stt-app-token
RUN_SA_NAME=omni-stt-run
REMOTE_REPO=ghcr
BUILD_REPO=omni-stt
LABEL_KEY=managed-by
LABEL_VAL=omni-stt-setup
MAX_STREAMS=4        # rooms one omni-stt instance takes (README, Cost model)
MAX_STREAMS_7B=6     # rooms one 7B instance takes (README, omni-stt-7b)

# Cloud Run regions with NVIDIA L4 GPUs, from Google's "GPU support for
# services" page (last updated 2026-10-26). us-east4 first: it is where this
# repository's own deploys got L4 quota on a new project.
REGIONS=(us-east4 us-central1 europe-west1 europe-west4 asia-southeast1 asia-south1)
REGION_NOTES=("Northern Virginia" "Iowa" "Belgium" "Netherlands" "Singapore" "Mumbai, invitation only")

NEW_TOKEN=0
for a in "$@"; do
  case "$a" in
    --new-token) NEW_TOKEN=1 ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d'; exit 0 ;;
    *) echo "unknown option: $a (see --help)" >&2; exit 2 ;;
  esac
done

DRY_RUN="${DRY_RUN:-0}"
say()  { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
die()  { printf '\nSTOPPED: %s\n' "$*" >&2; exit "${2:-1}"; }
# Commands that change something: printed, not run, in a dry run.
run() {
  if [ "$DRY_RUN" = 1 ]; then
    { printf '+'; printf ' %q' "$@"; printf '\n'; } >&2
  else
    "$@"
  fi
}
# A question with a default; ASSUME_YES=1 takes the default without asking.
ask() {
  local prompt="$1" def="$2" reply
  if [ "${ASSUME_YES:-0}" = 1 ] || [ ! -t 0 ]; then
    printf '%s [%s]: %s\n' "$prompt" "$def" "$def" >&2
    printf '%s' "$def"; return
  fi
  read -r -p "$prompt [$def]: " reply
  printf '%s' "${reply:-$def}"
}
yes_no() {
  case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
    y|yes) printf yes ;; n|no) printf no ;; *) return 1 ;;
  esac
}

# A failed gcloud call, said plainly: GPU quota, billing and organisation
# policy are the usual reasons a first deploy fails on a new project.
explain_failure() {
  local log="$1" what="$2"
  say ""
  if grep -qiE 'quota' "$log" && grep -qiE 'gpu|nvidia|l4' "$log"; then
    say "$what failed: the project has no Cloud Run L4 GPU quota left in $REGION."
    say "Request it (usually granted within a few days, often minutes):"
    say "  1. Open https://console.cloud.google.com/iam-admin/quotas?project=$PROJECT"
    say "  2. Filter: \"Total Nvidia L4 GPU allocation without zonal redundancy, per project per region\""
    say "     (service Cloud Run Admin API), and pick region $REGION."
    say "  3. Edit quota, ask for 1 (2 if you also deploy the 7B service), and submit."
    say "Then run this script again; it picks up where it stopped. Or try another region."
  elif grep -qiE 'billing' "$log"; then
    say "$what failed: billing is not enabled on $PROJECT."
    say "Link a billing account at https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT"
    say "then run this script again."
  elif grep -qiE 'constraints/|organization policy|org policy' "$log"; then
    say "$what failed: an organisation policy refused it. Ask your Google Cloud administrator;"
    say "the message below names the policy."
  elif grep -qiE 'PERMISSION_DENIED|does not have permission|forbidden' "$log"; then
    say "$what failed: your account lacks a permission on $PROJECT (Owner, or Editor plus"
    say "Project IAM Admin and Secret Manager Admin, is enough)."
  else
    say "$what failed:"
  fi
  say "---- gcloud said ----"
  tail -n 25 "$log"
  say "---------------------"
}
# gcloud run deploy, but a first deploy whose image copy (11 minutes for
# omni-stt from the ghcr proxy, measured 2026-10-28) outlasts gcloud's
# readiness deadline is not a failure: Cloud Run keeps going and the service
# turns Ready a minute later. Wait for that (up to 15 minutes) instead of
# stopping; anything else is explained and stops, as run_or_explain does.
deploy_service() {
  local name="$1"; shift
  if [ "$DRY_RUN" = 1 ]; then run gcloud run deploy "$name" "$@"; return; fi
  local log st i
  log="$(mktemp)"
  if gcloud run deploy "$name" "$@" 2> >(tee "$log" >&2); then rm -f "$log"; return; fi
  sleep 1
  if grep -qiE 'readiness deadline exceeded|deadline exceeded' "$log"; then
    say "The first deploy copies the image, which can outlast gcloud's wait; waiting for $name to come up..."
    for i in $(seq 1 90); do
      st="$(gcloud run services describe "$name" --project "$PROJECT" --region "$REGION" \
        --format 'value(status.conditions[0].status)' 2>/dev/null || true)"
      if [ "$st" = True ]; then say "$name is ready."; rm -f "$log"; return; fi
      sleep 10
    done
  fi
  explain_failure "$log" "Deploying $name"
  rm -f "$log"
  exit 1
}
# Run a changing gcloud command; on failure explain it and stop.
run_or_explain() {
  local what="$1"; shift
  if [ "$DRY_RUN" = 1 ]; then run "$@"; return; fi
  local log
  log="$(mktemp)"
  if ! "$@" 2> >(tee "$log" >&2); then
    sleep 1
    explain_failure "$log" "$what"
    rm -f "$log"
    exit 1
  fi
  rm -f "$log"
}

# images.env: KEY=value lines, read, never run. OMNI_STT_IMAGE=build in the
# environment skips it and builds omni-stt in your project instead.
OMNI_STT_IMAGE="${OMNI_STT_IMAGE:-}"
if [ "$OMNI_STT_IMAGE" = build ]; then
  OMNI_STT_IMAGE=""
elif [ -z "$OMNI_STT_IMAGE" ] && [ -f "$HERE/images.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in OMNI_STT_IMAGE=*) OMNI_STT_IMAGE="${line#OMNI_STT_IMAGE=}" ;; esac
  done < "$HERE/images.env"
fi
if [ -n "$OMNI_STT_IMAGE" ] && ! [[ "$OMNI_STT_IMAGE" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]]; then
  die "images.env: OMNI_STT_IMAGE must be ghcr.io/<owner>/<name>@sha256:<64 hex digits> (a pinned digest, not a tag)" 3
fi

say "Omnilingual hearing on Cloud Run: setup"
say "Nothing is changed until you confirm the plan below."

step "1/7 Google Cloud account and project"
command -v gcloud >/dev/null || die "gcloud is not installed. Use Cloud Shell (it has it) or https://cloud.google.com/sdk/docs/install"
account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1 || true)"
if [ -z "$account" ]; then
  die "gcloud is not signed in. In Cloud Shell click \"Authorize\" when asked, or run: gcloud auth login
Then run this script again."
fi
say "Signed in as $account."
case "${PROJECT:-}" in *"{{"*) PROJECT="" ;; esac  # a tutorial placeholder left unfilled
if [ -z "${PROJECT:-}" ]; then
  current="$(gcloud config get-value project 2>/dev/null || true)"
  say "Your projects (first 20):"
  gcloud projects list --format='value(projectId)' --limit 20 2>/dev/null | sed 's/^/  /' || true
  PROJECT="$(ask "Project ID to use" "${current:-}")"
fi
[[ "$PROJECT" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || die "\"$PROJECT\" is not a project ID (lower-case letters, digits and hyphens). Create one at https://console.cloud.google.com/projectcreate" 2
gcloud projects describe "$PROJECT" --format='value(projectId)' >/dev/null 2>&1 \
  || die "project $PROJECT was not found, or your account cannot see it."
billing="$(gcloud billing projects describe "$PROJECT" --format='value(billingEnabled)' 2>/dev/null || echo unknown)"
case "$billing" in
  True|true) say "Project $PROJECT, billing enabled." ;;
  False|false) die "billing is not enabled on $PROJECT. A GPU service needs it (there is no free tier for GPUs).
Link a billing account: https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT
then run this script again." 4 ;;
  *) say "Project $PROJECT (billing could not be checked from here; if it is off, the deploy will say so)." ;;
esac

step "2/7 Region"
if [ -z "${REGION:-}" ]; then
  say "Regions with Cloud Run L4 GPUs (pick the one closest to your rooms):"
  for i in "${!REGIONS[@]}"; do printf '  %d) %-16s %s\n' "$((i + 1))" "${REGIONS[$i]}" "${REGION_NOTES[$i]}"; done
  pick="$(ask "Region (number or name)" 1)"
  if [[ "$pick" =~ ^[0-9]+$ ]] && [ "$pick" -ge 1 ] && [ "$pick" -le "${#REGIONS[@]}" ]; then
    REGION="${REGIONS[$((pick - 1))]}"
  else
    REGION="$pick"
  fi
fi
ok=0
for r in "${REGIONS[@]}"; do [ "$r" = "$REGION" ] && ok=1; done
[ "$ok" = 1 ] || [ "${ALLOW_ANY_REGION:-0}" = 1 ] || die "$REGION has no Cloud Run L4 GPUs (as of 2026-10-26). Pick one of: ${REGIONS[*]}
(ALLOW_ANY_REGION=1 skips this check if Google has added regions since.)" 2
say "Region $REGION."

if [ -z "${WITH_7B:-}" ]; then
  say ""
  say "The 7B service hears Lao and Khmer much better than the base model. It is a second"
  say "L4 (about \$1 an hour while warm, \$0 idle), and its image is built once in your"
  say "project (about 50 minutes of Cloud Build)."
  WITH_7B="$(ask "Also deploy the 7B service for Lao and Khmer? (yes/no)" no)"
fi
WITH_7B="$(yes_no "$WITH_7B")" || die "WITH_7B must be yes or no" 2
if [ -z "${NONPROFIT:-}" ]; then
  say ""
  say "One Haitian Creole voice (MMS) is licensed for non-commercial use only (CC-BY-NC)."
  NONPROFIT="$(ask "Is this for a non-profit organisation? (yes/no)" no)"
fi
NONPROFIT="$(yes_no "$NONPROFIT")" || die "NONPROFIT must be yes or no" 2
if [ "$NONPROFIT" = yes ]; then EDITION=nonprofit; else EDITION=commercial; fi

if [ -n "$OMNI_STT_IMAGE" ]; then
  src="the published image (${OMNI_STT_IMAGE#*@}) through an Artifact Registry remote repository"
else
  src="built in your project with Cloud Build (about 30 minutes, once)"
fi
step "3/7 The plan"
say "Project:      $PROJECT"
say "Region:       $REGION"
say "omni-stt:     $src"
[ "$WITH_7B" = yes ] && say "omni-stt-7b:  built in your project with Cloud Build (about 50 minutes, once)"
say "Each service: 1 NVIDIA L4, 4 vCPU, 16 GiB, min 0 / max 1 instance, 1 h request timeout"
say "Edition:      $EDITION (the voices omni-stt may use)"
say "Cost:         about \$1 an hour per service while it is awake, \$0 while idle"
say "              (it sleeps about 15 minutes after the last room disconnects),"
say "              plus image storage, about \$0.10 per GB a month."
go="$(ask "Go ahead? (yes/no)" yes)"
[ "$(yes_no "$go" || true)" = yes ] || die "nothing was changed." 0

step "4/7 APIs and GPU quota"
apis=(run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com iam.googleapis.com cloudquotas.googleapis.com)
if [ -z "$OMNI_STT_IMAGE" ] || [ "$WITH_7B" = yes ]; then apis+=(cloudbuild.googleapis.com); fi
run_or_explain "Enabling the APIs" gcloud services enable "${apis[@]}" --project "$PROJECT"

# Best effort: the L4 quota in the region, before anything is built. New
# projects normally get a small grant at their first GPU deploy in a region, so
# "not listed" is fine, and even a 0 only earns a warning.
quota_check() {
  local json
  json="$(CLOUDSDK_CORE_DISABLE_PROMPTS=1 gcloud beta quotas info list --service=run.googleapis.com --project="$PROJECT" --format=json </dev/null 2>/dev/null)" || return 2
  QUOTA_JSON="$json" python3 - "$REGION" <<'PY'
import json, os, sys
region = sys.argv[1]
try:
    infos = json.loads(os.environ["QUOTA_JSON"])
except Exception:
    sys.exit(2)
for q in infos:
    if not str(q.get("metric", "")).endswith("nvidia_l4_gpu_allocation_no_zonal_redundancy"):
        continue
    for d in q.get("dimensionsInfos", []):
        if d.get("dimensions", {}).get("region") == region:
            v = d.get("details", {}).get("value")
            print(v)
            # -1 is unlimited; only an explicit 0 stops the setup.
            sys.exit(1 if v is not None and int(v) == 0 else 0)
sys.exit(0)
PY
}
need_gpus=1; [ "$WITH_7B" = yes ] && need_gpus=2
quota_rc=0; quota="$(quota_check)" || quota_rc=$?
if [ "$quota_rc" = 0 ]; then
  [ -n "$quota" ] && say "L4 quota in $REGION: $quota GPU(s)."
elif [ "$quota_rc" = 1 ]; then
  say "The project's Cloud Run L4 quota in $REGION reads 0. Google usually grants a few"
  say "GPUs at a project's first GPU deploy in a region, so it may still work; if the deploy"
  say "says quota, request it: https://console.cloud.google.com/iam-admin/quotas?project=$PROJECT"
  say "(\"Total Nvidia L4 GPU allocation without zonal redundancy, per project per region\","
  say "region $REGION, Edit quota, ask for $need_gpus)."
  cont="$(ask "Continue anyway? (yes/no)" yes)"
  [ "$(yes_no "$cont" || true)" = yes ] || die "stopped before building or deploying anything; run again once the quota is granted." 5
else
  say "(The GPU quota could not be checked from here; the deploy will tell you if it is missing.)"
fi


step "5/7 Service account and access token"
RUN_SA="$RUN_SA_NAME@$PROJECT.iam.gserviceaccount.com"
if gcloud iam service-accounts describe "$RUN_SA" --project "$PROJECT" >/dev/null 2>&1; then
  say "Service account $RUN_SA_NAME exists."
else
  run_or_explain "Creating the service account" gcloud iam service-accounts create "$RUN_SA_NAME" \
    --project "$PROJECT" --display-name "omni-stt on Cloud Run (setup.sh)"
fi
TOKEN=""
# token-shown=no until the token is printed at the end: a run that stopped
# before then stored a token nobody saw, so the next run replaces it.
if secret_labels="$(gcloud secrets describe "$SECRET_NAME" --project "$PROJECT" --format='value(labels)' 2>/dev/null)"; then
  case ";$secret_labels;" in
    *";token-shown=no;"*)
      [ "$NEW_TOKEN" = 1 ] || say "An earlier run stopped before showing its token; making a new one."
      NEW_TOKEN=1 ;;
  esac
  if [ "$NEW_TOKEN" = 1 ]; then
    TOKEN="$(openssl rand -hex 32)"
    if [ "$DRY_RUN" = 1 ]; then run gcloud secrets versions add "$SECRET_NAME" --data-file=- --project "$PROJECT"
    else printf '%s' "$TOKEN" | run_or_explain "Replacing the token" gcloud secrets versions add "$SECRET_NAME" --data-file=- --project "$PROJECT" >/dev/null; fi
    run gcloud secrets update "$SECRET_NAME" --update-labels token-shown=no --project "$PROJECT" >/dev/null
    say "A new token was stored (the old one stops working when the services restart below)."
  else
    say "The access token exists (secret $SECRET_NAME); it was shown when it was made."
    say "Lost it? Run this script again with --new-token."
  fi
else
  TOKEN="$(openssl rand -hex 32)"
  if [ "$DRY_RUN" = 1 ]; then
    run gcloud secrets create "$SECRET_NAME" --data-file=- --replication-policy automatic --labels "$LABEL_KEY=$LABEL_VAL,token-shown=no" --project "$PROJECT"
  else
    printf '%s' "$TOKEN" | run_or_explain "Storing the token" gcloud secrets create "$SECRET_NAME" --data-file=- \
      --replication-policy automatic --labels "$LABEL_KEY=$LABEL_VAL,token-shown=no" --project "$PROJECT" >/dev/null
  fi
  say "A new access token was stored in Secret Manager ($SECRET_NAME)."
fi
run_or_explain "Letting the service account read the token" gcloud secrets add-iam-policy-binding "$SECRET_NAME" \
  --project "$PROJECT" --member "serviceAccount:$RUN_SA" --role roles/secretmanager.secretAccessor --condition=None >/dev/null

# Cloud Build runs as the project's default compute service account, which a
# new project (in an organisation made since 2024) creates with no roles at all:
# the build then cannot read its own uploaded source ("storage.objects.get
# access ... denied"). Give it the Cloud Build role now, so the grant has
# reached Cloud Build by the time a build starts.
ensure_builder() {
  local num
  num="$(gcloud projects describe "$PROJECT" --format 'value(projectNumber)')"
  say "Letting Cloud Build's service account ($num-compute@...) build and push images." >&2
  run_or_explain "Granting Cloud Build its role" gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:$num-compute@developer.gserviceaccount.com" \
    --role roles/cloudbuild.builds.builder --condition=None >/dev/null
}
if [ -z "$OMNI_STT_IMAGE" ] || [ "$WITH_7B" = yes ]; then ensure_builder; fi

step "6/7 Images"
ensure_repo() {  # name, then extra create flags
  local name="$1"; shift
  if gcloud artifacts repositories describe "$name" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1; then
    say "Artifact Registry repository $name exists in $REGION."
  else
    # Just after the API is enabled on a new project, Artifact Registry can
    # refuse its owner for a minute or two (PERMISSION_DENIED, measured
    # 2026-10-28): try again for up to 5 minutes before explaining it.
    local i
    for i in 1 2 3 4 5 6 7 8 9 10; do
      [ "$DRY_RUN" = 1 ] && break
      gcloud artifacts repositories list --location "$REGION" --project "$PROJECT" --limit 1 >/dev/null 2>&1 && break
      [ "$i" = 1 ] && say "Artifact Registry is not ready for this project yet (normal right after enabling it); waiting..."
      sleep 30
    done
    run_or_explain "Creating the Artifact Registry repository $name" gcloud artifacts repositories create "$name" \
      --repository-format docker --location "$REGION" --project "$PROJECT" --labels "$LABEL_KEY=$LABEL_VAL" "$@"
  fi
}
# The digest of an image in this project's registry, or empty.
digest_of() {
  gcloud artifacts docker images describe "$1" --project "$PROJECT" --format 'value(image_summary.digest)' 2>/dev/null || true
}
TAG="$(git -C "$ROOT" rev-parse --short=12 HEAD 2>/dev/null || true)"
build_image() {  # deploy.sh command, image tag suffix; prints the image by digest
  local cmd="$1" suffix="$2" ref digest
  [ -n "$TAG" ] || die "this folder is not a git checkout, so the build has no tag; use the Open in Cloud Shell button or git clone"
  ref="$REGION-docker.pkg.dev/$PROJECT/$BUILD_REPO/omni-stt:$TAG$suffix"
  digest="$(digest_of "$ref")"
  if [ -z "$digest" ]; then
    say "Building $ref with Cloud Build (the log streams below; closing Cloud Shell does not stop it)." >&2
    # PRIVATE_ENV: a maintainer's private.env never reaches this build.
    if ! env PRIVATE_ENV=/nonexistent PROJECT="$PROJECT" REGION="$REGION" REPO_REGION="$REGION" REPO="$BUILD_REPO" \
         SERVICE=omni-stt TAG="$TAG" DRY_RUN="$DRY_RUN" bash "$SVC_DIR/deploy.sh" "$cmd" >&2; then
      die "the Cloud Build build failed (its log is above, and at https://console.cloud.google.com/cloud-build/builds?project=$PROJECT).
Run this script again to retry; a finished image is never rebuilt."
    fi
    digest="$(digest_of "$ref")"
    if [ -z "$digest" ]; then
      [ "$DRY_RUN" = 1 ] || die "the build finished but $ref is not in the registry"
      digest="sha256:dry-run"
    fi
  else
    say "Image $ref is already built." >&2
  fi
  printf '%s@%s' "${ref%:*}" "$digest"
}
if [ -n "$OMNI_STT_IMAGE" ]; then
  ensure_repo "$REMOTE_REPO" --mode remote-repository --remote-docker-repo https://ghcr.io \
    --remote-repo-config-desc "GitHub Container Registry (public images)" \
    --description "Proxy of ghcr.io for the omni-stt image (setup.sh)"
  IMAGE="$REGION-docker.pkg.dev/$PROJECT/$REMOTE_REPO/${OMNI_STT_IMAGE#ghcr.io/}"
  say "omni-stt image: $IMAGE"
else
  ensure_repo "$BUILD_REPO" --description "omni-stt images built by setup.sh"
  IMAGE="$(build_image build "")"
  say "omni-stt image: $IMAGE"
fi
if [ "$WITH_7B" = yes ] && [ -n "$OMNI_STT_IMAGE" ]; then
  ensure_repo "$BUILD_REPO" --description "omni-stt images built by setup.sh"
fi

url_of() {
  if [ "$DRY_RUN" = 1 ]; then printf 'https://%s-(dry-run).run.app' "$1"; return; fi
  gcloud run services describe "$1" --project "$PROJECT" --region "$REGION" --format 'value(status.url)'
}

# The token, printed once: here at the end, or, while the 7B builds, as soon
# as omni-stt is up (so Live Translation can use it an hour sooner).
TOKEN_SHOWN=0
show_token() {
  if [ "$TOKEN_SHOWN" = 1 ]; then
    printf '  Token:                                 (shown above, when %s came up)\n' "$SERVICE"
    return
  fi
  TOKEN_SHOWN=1
  if [ -n "$TOKEN" ]; then
    if [ "$DRY_RUN" = 1 ]; then
      printf '  Token:                                 (shown here in a real run)\n'
    else
      printf '  Token:                                 %s\n' "$TOKEN"
      gcloud secrets update "$SECRET_NAME" --update-labels token-shown=yes --project "$PROJECT" >/dev/null 2>&1 || true
      cat <<'EOF'

  COPY THE TOKEN NOW. It is shown only this once; Live Translation stores
  it encrypted and never shows it again. Lost it: run this script again
  with --new-token, then paste the new one.
EOF
    fi
  else
    printf '  Token:                                 (unchanged: the one you pasted before)\n'
  fi
}

step "7/7 Deploying"
# Flags shared by both services. --no-cpu-throttling: CPU stays allocated (a
# GPU service needs it, and the VAD runs between messages). --timeout 3600:
# Cloud Run's ceiling; a room's WebSocket reconnects after an hour.
# --no-gpu-zonal-redundancy: cheaper, and the quota new projects get.
# --no-invoker-iam-check: the service checks its own token (Live Translation
# cannot attach a Google identity token to a WebSocket).
common=(--project "$PROJECT" --region "$REGION" --service-account "$RUN_SA"
  --gpu 1 --gpu-type nvidia-l4 --no-gpu-zonal-redundancy
  --cpu 4 --memory 16Gi --no-cpu-throttling --cpu-boost
  --min-instances 0 --max-instances 1 --timeout 3600 --port 8080
  --set-secrets "STT_TOKEN_NONPROFIT=$SECRET_NAME:latest"
  --labels "$LABEL_KEY=$LABEL_VAL" --no-invoker-iam-check --quiet)
# Endpointing and batching as deploy.sh's defaults (README, Endpointing).
tuning="ENDPOINT_MS=200,MAX_UTTERANCE_S=10.0,MIN_SPEECH_MS=1000,STT_BATCH_MAX=8,STT_BATCH_WAIT_MS=10"
say "Deploying $SERVICE (the first deploy copies the image: 10-15 minutes)..."
deploy_service "$SERVICE" --image "$IMAGE" "${common[@]}" \
  --concurrency "$MAX_STREAMS" \
  --set-env-vars "STT_MAX_CONNECTIONS=$MAX_STREAMS,OMNI_CARD=omniASR_LLM_300M,HT_VOICE=coqui,EDITION=$EDITION,STT_MAX_SPEAKERS=4,$tuning"
say "$SERVICE is deployed: $(url_of "$SERVICE")"
if [ "$WITH_7B" = yes ]; then
  if [ -n "$TOKEN" ]; then
    say ""
    say "omni-stt works now. Its settings, while the 7B builds (the 7B URL follows at the end):"
    say "  Service:                               $(url_of "$SERVICE")"
    show_token
  fi
  # Built after omni-stt is up, so the hour-long 7B build does not hold it back.
  say "Now the 7B image (about 50 minutes of Cloud Build; omni-stt already works meanwhile)."
  IMAGE_7B="$(build_image 7b-build -7b)"
  say "omni-stt-7b image: $IMAGE_7B"
  say "Deploying $SERVICE_7B..."
  # The startup probe: the port opens once the 16 GB checkpoint is loaded and
  # warm (about 50 s from cold); checked every 2 s, for up to 15 minutes.
  deploy_service "$SERVICE_7B" --image "$IMAGE_7B" "${common[@]}" \
    --concurrency "$MAX_STREAMS_7B" \
    --startup-probe "tcpSocket.port=8080,initialDelaySeconds=0,periodSeconds=2,timeoutSeconds=2,failureThreshold=450" \
    --set-env-vars "STT_SERVE=listen,STT_MAX_CONNECTIONS=$MAX_STREAMS_7B,OMNI_CARD=omniASR_LLM_7B_bf16,OMNI_MMAP=1,$tuning"
fi

URL="$(url_of "$SERVICE")"
URL_7B=""; [ "$WITH_7B" = yes ] && URL_7B="$(url_of "$SERVICE_7B")"

cat <<EOF

=====================================================================
 Done. Paste these into Live Translation:
   Service settings > Advanced > Omnilingual hearing (advanced)
=====================================================================
  Service:                               $URL
EOF
[ -n "$URL_7B" ] && printf '  Omnilingual 7B URL for Lao and Khmer:  %s\n' "$URL_7B"
show_token
cap_7b=""; [ -n "$URL_7B" ] && cap_7b=", the 7B about $MAX_STREAMS_7B"
cat <<EOF

  Then turn on "Hear Haitian Creole with Omnilingual" and press Test: it
  wakes the service(s) (about 40 s for omni-stt, 50 s for the 7B) and checks
  the token. One instance of omni-stt takes about $MAX_STREAMS rooms at once$cap_7b.

  Cost: about \$1 an hour per service while it is awake, \$0 while idle.
  Remove everything: bash services/omni-stt/cloudrun/teardown.sh
EOF
