#!/usr/bin/env bash
set -e

PROJECT_ID="macrobot-503307"
BUCKET_NAME="macrobot-state-bucket"
REGION="us-central1"

if [ -f .env ]; then
  echo "Loading variables from .env file..."
  export $(grep -v '^#' .env | xargs)
fi

FRED_API_KEY="${FRED_API_KEY:-}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-claude-3-5-sonnet-20241022}"
DISCORD_WEBHOOK_URL="${DISCORD_WEBHOOK_URL:-}"
TIMEZONE="${TIMEZONE:-America/New_York}"
LOG_LEVEL="${LOG_LEVEL:-INFO}"

echo "Setting project context..."
gcloud config set project "$PROJECT_ID"

echo "Enabling GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  storage.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com

echo "Creating Artifact Registry repository..."
gcloud artifacts repositories create macrobot-repo \
  --repository-format=docker \
  --location="$REGION" \
  --description="Docker repository for macrobot" || true

echo "Building container image using Cloud Build..."
gcloud builds submit --tag "$REGION-docker.pkg.dev/$PROJECT_ID/macrobot-repo/macrobot:latest" .

echo "Deploying Cloud Run Job..."
gcloud run jobs deploy macrobot-job \
  --image "$REGION-docker.pkg.dev/$PROJECT_ID/macrobot-repo/macrobot:latest" \
  --region "$REGION" \
  --set-env-vars "GCS_BUCKET_NAME=$BUCKET_NAME,FRED_API_KEY=$FRED_API_KEY,ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY,ANTHROPIC_MODEL=$ANTHROPIC_MODEL,DISCORD_WEBHOOK_URL=$DISCORD_WEBHOOK_URL,TIMEZONE=$TIMEZONE,LOG_LEVEL=$LOG_LEVEL"

echo "Granting GCS Bucket permissions to default Compute service account..."
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET_NAME" \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

echo "Creating Cloud Scheduler trigger (hourly)..."
gcloud scheduler jobs create http macrobot-hourly-schedule \
  --location="$REGION" \
  --schedule="0 * * * *" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/macrobot-job:run" \
  --http-method=POST \
  --oauth-service-account-email="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" || \
gcloud scheduler jobs update http macrobot-hourly-schedule \
  --location="$REGION" \
  --schedule="0 * * * *" \
  --uri="https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/macrobot-job:run" \
  --http-method=POST \
  --oauth-service-account-email="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "Running initial test execution of Cloud Run Job..."
gcloud run jobs execute macrobot-job --region "$REGION"

echo "Deployment complete!"
