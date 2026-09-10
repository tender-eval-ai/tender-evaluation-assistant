#!/usr/bin/env bash
# One-time GCP setup for the Cloud Run demo (idempotent — safe to re-run).
# Creates: Artifact Registry repo, GCS data bucket, runtime service account with
# the least roles it needs, the API_KEY secret (random, never printed), and seeds
# the bucket's inbox with the synthetic demo cases.
# Needs: gcloud logged in, `gcloud config set project <id>`, billing linked.
set -euo pipefail
cd "$(dirname "$0")/../.."

PROJECT=${PROJECT:-$(gcloud config get-value project 2>/dev/null)}
REGION=${REGION:-us-central1}
REPO=${REPO:-tender}
BUCKET=${BUCKET:-${PROJECT}-data}
SA=${SA:-tender-run}
SECRET=${SECRET:-tender-api-key}
SA_EMAIL="${SA}@${PROJECT}.iam.gserviceaccount.com"
NUMBER=$(gcloud projects describe "$PROJECT" --format="value(projectNumber)")

echo "== APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
    cloudbuild.googleapis.com secretmanager.googleapis.com compute.googleapis.com \
    aiplatform.googleapis.com storage.googleapis.com --project "$PROJECT"

echo "== Artifact Registry repo $REPO"
gcloud artifacts repositories describe "$REPO" --location "$REGION" --project "$PROJECT" >/dev/null 2>&1 ||
    gcloud artifacts repositories create "$REPO" --repository-format docker --location "$REGION" \
        --description "Tender Evaluation Assistant images" --project "$PROJECT"

echo "== Bucket gs://$BUCKET (single region, uniform access, no public access)"
gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT" >/dev/null 2>&1 ||
    gcloud storage buckets create "gs://$BUCKET" --location "$REGION" --project "$PROJECT" \
        --uniform-bucket-level-access --public-access-prevention

echo "== Runtime service account $SA_EMAIL"
gcloud iam service-accounts describe "$SA_EMAIL" --project "$PROJECT" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "$SA" --display-name "Tender demo (Cloud Run runtime)" --project "$PROJECT"
# Vertex AI calls (Gemini) — project level; bucket read/write — bucket level only.
# (A just-created account takes a few seconds to become bindable: retry.)
for attempt in 1 2 3 4 5 6; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member "serviceAccount:$SA_EMAIL" \
        --role roles/aiplatform.user --condition None --quiet >/dev/null 2>&1 && break
    echo "   (waiting for the service account to propagate, attempt $attempt)"; sleep 5
done
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member "serviceAccount:$SA_EMAIL" \
    --role roles/storage.objectAdmin --project "$PROJECT" >/dev/null

echo "== Secret $SECRET (X-API-Key shared by backend and frontend)"
if ! gcloud secrets describe "$SECRET" --project "$PROJECT" >/dev/null 2>&1; then
    openssl rand -hex 24 | tr -d '\n' | gcloud secrets create "$SECRET" --data-file - \
        --replication-policy automatic --project "$PROJECT"
fi
gcloud secrets add-iam-policy-binding "$SECRET" --member "serviceAccount:$SA_EMAIL" \
    --role roles/secretmanager.secretAccessor --project "$PROJECT" >/dev/null

echo "== Cloud Build: let the build account push images and write logs"
gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:${NUMBER}-compute@developer.gserviceaccount.com" \
    --role roles/cloudbuild.builds.builder --condition None --quiet >/dev/null

echo "== Seed the server inbox with the synthetic demo cases"
for case in demo_case demo_case_stress; do
    if [ -d "$case" ]; then
        gcloud storage rsync -r "$case" "gs://$BUCKET/inbox/$case" --project "$PROJECT" >/dev/null
    else
        echo "   skipping $case — not present (regenerate: python tools/make_demo_case.py --bidders 30 --out demo_case_stress)"
    fi
done
echo "done: project=$PROJECT region=$REGION repo=$REPO bucket=$BUCKET sa=$SA_EMAIL secret=$SECRET"
