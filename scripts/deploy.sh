#!/usr/bin/env bash
# Deploys Disha to Cloud Run as a temporary public demo.
#
# Every resource this script creates is recorded in .deploy/state.env, so that
# scripts/teardown.sh removes exactly those resources and nothing that existed before.
#
# Usage:
#   PROJECT_ID=my-project ./scripts/deploy.sh
# Options (env vars):
#   REGION=us-central1        Live API native-audio models are served from us-central1.
#   SERVICE=snapdeal-virtual-kam
#   LIVE_MODEL=gemini-3.8-live
#   VOICE_NAME=Kore
#   PUBLIC=true               false = require IAM auth to invoke (not shareable).
#   EXPIRES=YYYY-MM-DD        Label only; reminds you when to run teardown.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || true)}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-snapdeal-virtual-kam}"
REPO="${REPO:-snapdeal-virtual-kam}"
SA_NAME="${SA_NAME:-vkam-run}"
LIVE_MODEL="${LIVE_MODEL:-gemini-3.8-live}"
VOICE_NAME="${VOICE_NAME:-Kore}"
PUBLIC="${PUBLIC:-true}"
EXPIRES="${EXPIRES:-$(date -u -d '+2 days' +%Y-%m-%d 2>/dev/null || date -u -v+2d +%Y-%m-%d)}"
APIS=(run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com aiplatform.googleapis.com)

STATE_DIR="$ROOT/.deploy"
STATE_FILE="$STATE_DIR/state.env"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# Persist a key=value pair to the state file (last write wins when sourced).
record() { printf '%s=%q\n' "$1" "$2" >> "$STATE_FILE"; }

[[ -n "$PROJECT_ID" ]] || die "Set PROJECT_ID (or run: gcloud config set project <id>)."
command -v gcloud >/dev/null || die "gcloud CLI not found."
gcloud auth print-access-token >/dev/null 2>&1 || die "gcloud is not authenticated. Run: gcloud auth login"

mkdir -p "$STATE_DIR"
if [[ ! -f "$STATE_FILE" ]]; then
  {
    echo "# Created by scripts/deploy.sh on $(date -u +%FT%TZ). Used by scripts/teardown.sh."
  } > "$STATE_FILE"
fi
record PROJECT_ID "$PROJECT_ID"
record REGION "$REGION"
record SERVICE "$SERVICE"
record REPO "$REPO"

SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%s)"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/app:$TAG"
STAGING_BUCKET="gs://${PROJECT_ID}_cloudbuild"
STAGING_PREFIX="$STAGING_BUCKET/snapdeal-virtual-kam-source"

log "Project $PROJECT_ID, region $REGION, service $SERVICE, model $LIVE_MODEL"

# --- 1. APIs ---------------------------------------------------------------------------
log "Enabling required APIs (only those not already enabled are recorded for teardown)"
ENABLED="$(gcloud services list --enabled --project "$PROJECT_ID" --format='value(config.name)')"
for api in "${APIS[@]}"; do
  if ! grep -qx "$api" <<<"$ENABLED"; then
    gcloud services enable "$api" --project "$PROJECT_ID"
    record "ENABLED_API_${api%%.*}" "$api"
  fi
done

# --- 2. Artifact Registry repository (dedicated, so teardown can delete it whole) -------
if ! gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  log "Creating Artifact Registry repo $REPO"
  gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION" \
    --project "$PROJECT_ID" --description "Temporary: Snapdeal Virtual KAM demo (expires $EXPIRES)" \
    --labels "app=snapdeal-vkam,purpose=temp-demo"
  record REPO_CREATED 1
fi

# --- 3. Least-privilege runtime service account ---------------------------------------
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project "$PROJECT_ID" >/dev/null 2>&1; then
  log "Creating service account $SA_EMAIL"
  gcloud iam service-accounts create "$SA_NAME" --project "$PROJECT_ID" \
    --display-name "Snapdeal Virtual KAM (temporary demo)"
  record SA_CREATED 1
  sleep 5 # IAM propagation
fi
record SA_EMAIL "$SA_EMAIL"
log "Granting roles/aiplatform.user to the runtime service account"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$SA_EMAIL" \
  --role roles/aiplatform.user --condition None --quiet >/dev/null
record IAM_BINDING_ADDED 1

# --- 4. Build the container with Cloud Build ------------------------------------------
if ! gcloud storage buckets describe "$STAGING_BUCKET" --project "$PROJECT_ID" >/dev/null 2>&1; then
  log "Creating Cloud Build staging bucket $STAGING_BUCKET"
  gcloud storage buckets create "$STAGING_BUCKET" --project "$PROJECT_ID" --location "$REGION" \
    --uniform-bucket-level-access --public-access-prevention
  record STAGING_BUCKET_CREATED 1
fi
record STAGING_PREFIX "$STAGING_PREFIX"
log "Building $IMAGE"
gcloud builds submit --project "$PROJECT_ID" --region "$REGION" --tag "$IMAGE" \
  --gcs-source-staging-dir "$STAGING_PREFIX" .

# --- 5. Deploy to Cloud Run ------------------------------------------------------------
AUTH_FLAG="--no-allow-unauthenticated"
[[ "$PUBLIC" == "true" ]] && AUTH_FLAG="--allow-unauthenticated"
log "Deploying Cloud Run service $SERVICE"
record SERVICE_DEPLOYED 1
gcloud run deploy "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --service-account "$SA_EMAIL" \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$REGION,LIVE_MODEL=$LIVE_MODEL,VOICE_NAME=$VOICE_NAME,MAX_CALL_SECONDS=600,MAX_CONCURRENT_CALLS=6" \
  --timeout 3600 --concurrency 10 --cpu 1 --memory 512Mi --cpu-boost \
  --min-instances 0 --max-instances 3 \
  --labels "app=snapdeal-vkam,purpose=temp-demo,expires=$EXPIRES" \
  "$AUTH_FLAG"

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')"
record URL "$URL"
record DEPLOYED_AT "$(date -u +%FT%TZ)"

if [[ "$PUBLIC" == "true" ]]; then
  if gcloud run services get-iam-policy "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
      --format 'value(bindings.members)' | grep -q allUsers; then
    log "Done. Public demo URL: $URL"
  else
    warn "The service deployed, but public access could not be granted (likely an org policy)."
    warn "It is NOT reachable by external users. Do not work around the policy; use a project that allows it."
  fi
else
  log "Done (private). URL: $URL"
fi
echo "Health check:  curl -s $URL/healthz"
echo "Remove everything later with:  ./scripts/teardown.sh"
