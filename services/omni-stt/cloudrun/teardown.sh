#!/usr/bin/env bash
# Remove what setup.sh made: the omni-stt and omni-stt-7b Cloud Run services,
# the access token's secret, the service account, and the Artifact Registry
# repositories (the ghcr.io proxy and the built images). Only things carrying
# setup.sh's label (managed-by=omni-stt-setup) are deleted, so a service or
# repository you made yourself with the same name is left alone and reported.
#
#   bash services/omni-stt/cloudrun/teardown.sh
#
# PROJECT and REGION from the environment skip their questions; ASSUME_YES=1
# skips the confirmation; DRY_RUN=1 prints the deletions instead of running them.
# The APIs stay enabled (they cost nothing). Deleting the whole project instead
# also removes everything: https://console.cloud.google.com/iam-admin/settings
set -euo pipefail

SERVICES=(omni-stt omni-stt-7b)
SECRET_NAME=omni-stt-app-token
RUN_SA_NAME=omni-stt-run
REPOS=(ghcr omni-stt)
LABEL='managed-by=omni-stt-setup'
DRY_RUN="${DRY_RUN:-0}"

say() { printf '%s\n' "$*"; }
run() {
  if [ "$DRY_RUN" = 1 ]; then printf '+'; printf ' %q' "$@"; printf '\n'; else "$@"; fi
}
ask() {
  local prompt="$1" def="$2" reply
  if [ "${ASSUME_YES:-0}" = 1 ] || [ ! -t 0 ]; then printf '%s' "$def"; return; fi
  read -r -p "$prompt [$def]: " reply
  printf '%s' "${reply:-$def}"
}
labelled() {  # the labels value of a describe, then: does it carry setup.sh's label
  case ";$1;" in *";$LABEL;"*) return 0 ;; *) return 1 ;; esac
}

command -v gcloud >/dev/null || { say "gcloud is not installed." >&2; exit 1; }
PROJECT="${PROJECT:-$(ask "Project ID" "$(gcloud config get-value project 2>/dev/null || true)")}"
REGION="${REGION:-$(ask "Region the services are in" us-east4)}"
[[ "$PROJECT" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || { say "\"$PROJECT\" is not a project ID" >&2; exit 2; }
[[ "$REGION" =~ ^[a-z]+-[a-z]+[0-9]+$ ]] || { say "\"$REGION\" is not a region" >&2; exit 2; }

found=()
skipped=()
for s in "${SERVICES[@]}"; do
  labels="$(gcloud run services describe "$s" --project "$PROJECT" --region "$REGION" \
    --format='value(metadata.labels)' 2>/dev/null)" || continue
  if labelled "$labels"; then found+=("service:$s"); else skipped+=("Cloud Run service $s (not made by setup.sh)"); fi
done
if labels="$(gcloud secrets describe "$SECRET_NAME" --project "$PROJECT" --format='value(labels)' 2>/dev/null)"; then
  if labelled "$labels"; then found+=("secret:$SECRET_NAME"); else skipped+=("secret $SECRET_NAME (not made by setup.sh)"); fi
fi
RUN_SA="$RUN_SA_NAME@$PROJECT.iam.gserviceaccount.com"
if gcloud iam service-accounts describe "$RUN_SA" --project "$PROJECT" --format='value(displayName)' 2>/dev/null | grep -q 'setup.sh'; then
  found+=("sa:$RUN_SA")
fi
for r in "${REPOS[@]}"; do
  labels="$(gcloud artifacts repositories describe "$r" --location "$REGION" --project "$PROJECT" \
    --format='value(labels)' 2>/dev/null)" || continue
  if labelled "$labels"; then found+=("repo:$r"); else skipped+=("Artifact Registry repository $r (not made by setup.sh)"); fi
done

for s in ${skipped[@]+"${skipped[@]}"}; do say "Leaving alone: $s"; done
if [ "${#found[@]}" = 0 ]; then
  say "Nothing made by setup.sh was found in $PROJECT ($REGION)."
  exit 0
fi
say "This deletes, in $PROJECT ($REGION):"
for f in "${found[@]}"; do say "  ${f%%:*}  ${f#*:}"; done
say "Live Translation's Omnilingual settings stop working once these are gone."
confirm="$(ask "Type the project ID to delete them" "")"
if [ "${ASSUME_YES:-0}" != 1 ] && [ "$confirm" != "$PROJECT" ]; then
  say "Nothing deleted."
  exit 0
fi

for f in "${found[@]}"; do
  kind="${f%%:*}"; name="${f#*:}"
  case "$kind" in
    service) run gcloud run services delete "$name" --project "$PROJECT" --region "$REGION" --quiet ;;
    secret)  run gcloud secrets delete "$name" --project "$PROJECT" --quiet ;;
    sa)      run gcloud iam service-accounts delete "$name" --project "$PROJECT" --quiet ;;
    repo)    run gcloud artifacts repositories delete "$name" --location "$REGION" --project "$PROJECT" --quiet ;;
  esac
done
say ""
say "Done. Cloud Build keeps its source uploads (a few MB) in the bucket ${PROJECT}_cloudbuild;"
say "delete it in Cloud Storage if you like. The APIs stay enabled; they cost nothing."
say "If setup.sh built an image, Cloud Build's service account keeps the Cloud Build role it"
say "was given (it costs nothing). Deleting the project removes all of it."
