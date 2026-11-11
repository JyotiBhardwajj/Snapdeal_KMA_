#!/usr/bin/env bash
# Removes everything scripts/deploy.sh created, using the record in .deploy/state.env.
# Pre-existing resources (APIs that were already on, shared buckets, other images) are left alone.
#
# Usage:
#   ./scripts/teardown.sh            # shows the plan and asks for confirmation
#   ./scripts/teardown.sh --yes      # no prompt
#   ./scripts/teardown.sh --yes --disable-apis   # also disable APIs that deploy.sh had to enable
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_FILE="$ROOT/.deploy/state.env"
ASSUME_YES=false
DISABLE_APIS=false
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=true ;;
    --disable-apis) DISABLE_APIS=true ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
try() { "$@" || printf '\033[1;33m   (skipped: %s)\033[0m\n' "$*" >&2; }

[[ -f "$STATE_FILE" ]] || die "No deployment record at $STATE_FILE. See README 'Manual teardown' for the commands."
# shellcheck disable=SC1090
source "$STATE_FILE"
: "${PROJECT_ID:?missing in state}" "${REGION:?missing in state}" "${SERVICE:?missing in state}"

ENABLED_APIS=()
while IFS='=' read -r key value; do
  [[ "$key" == ENABLED_API_* ]] && ENABLED_APIS+=("${value//\'/}")
done < "$STATE_FILE"

echo "Project:   $PROJECT_ID ($REGION)"
echo "Will delete:"
[[ "${SERVICE_DEPLOYED:-0}" == 1 ]] && echo "  - Cloud Run service        $SERVICE"
[[ "${IAM_BINDING_ADDED:-0}" == 1 ]] && echo "  - IAM binding              roles/aiplatform.user -> ${SA_EMAIL:-}"
[[ "${SA_CREATED:-0}" == 1 ]] && echo "  - Service account          ${SA_EMAIL:-}"
[[ "${REPO_CREATED:-0}" == 1 ]] && echo "  - Artifact Registry repo   ${REPO:-} (and its images)"
[[ -n "${STAGING_PREFIX:-}" ]] && echo "  - Cloud Build sources      ${STAGING_PREFIX}/"
[[ "${STAGING_BUCKET_CREATED:-0}" == 1 ]] && echo "  - Cloud Build bucket       gs://${PROJECT_ID}_cloudbuild (only if empty)"
if [[ ${#ENABLED_APIS[@]} -gt 0 ]]; then
  if $DISABLE_APIS; then echo "  - Disable APIs             ${ENABLED_APIS[*]}"
  else echo "  (APIs enabled by deploy.sh are kept: ${ENABLED_APIS[*]}; pass --disable-apis to disable)"; fi
fi

if ! $ASSUME_YES; then
  read -r -p $'\nProceed? [y/N] ' answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }
fi

if [[ "${SERVICE_DEPLOYED:-0}" == 1 ]]; then
  log "Deleting Cloud Run service $SERVICE"
  try gcloud run services delete "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --quiet
fi

if [[ "${IAM_BINDING_ADDED:-0}" == 1 && -n "${SA_EMAIL:-}" ]]; then
  log "Removing IAM binding for $SA_EMAIL"
  try gcloud projects remove-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA_EMAIL" \
    --role roles/aiplatform.user --condition None --quiet >/dev/null
fi

if [[ "${SA_CREATED:-0}" == 1 && -n "${SA_EMAIL:-}" ]]; then
  log "Deleting service account $SA_EMAIL"
  try gcloud iam service-accounts delete "$SA_EMAIL" --project "$PROJECT_ID" --quiet
fi

if [[ "${REPO_CREATED:-0}" == 1 && -n "${REPO:-}" ]]; then
  log "Deleting Artifact Registry repo $REPO"
  try gcloud artifacts repositories delete "$REPO" --location "$REGION" --project "$PROJECT_ID" --quiet
fi

if [[ -n "${STAGING_PREFIX:-}" ]]; then
  log "Deleting staged Cloud Build sources under $STAGING_PREFIX/"
  try gcloud storage rm --recursive "$STAGING_PREFIX/" --project "$PROJECT_ID" --quiet
fi

if [[ "${STAGING_BUCKET_CREATED:-0}" == 1 ]]; then
  if [[ -z "$(gcloud storage ls "gs://${PROJECT_ID}_cloudbuild/" --project "$PROJECT_ID" 2>/dev/null)" ]]; then
    log "Deleting empty bucket gs://${PROJECT_ID}_cloudbuild"
    try gcloud storage buckets delete "gs://${PROJECT_ID}_cloudbuild" --project "$PROJECT_ID" --quiet
  fi
fi

if $DISABLE_APIS; then
  for api in "${ENABLED_APIS[@]}"; do
    log "Disabling $api"
    try gcloud services disable "$api" --project "$PROJECT_ID" --quiet
  done
fi

log "Verifying nothing labelled app=snapdeal-vkam is left"
try gcloud run services list --project "$PROJECT_ID" --region "$REGION" --filter "metadata.labels.app=snapdeal-vkam" \
  --format "value(metadata.name)"

mv "$STATE_FILE" "$STATE_FILE.removed-$(date -u +%Y%m%dT%H%M%SZ)"
log "Teardown complete."
