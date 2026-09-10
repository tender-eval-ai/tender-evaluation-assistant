#!/usr/bin/env bash
# Build (Cloud Build) and deploy the demo as ONE private Cloud Run service with three
# containers: nginx ingress (:8080) -> backend (:8000, /api/*) + frontend (:8501, /*).
#   bash deploy/cloudrun/setup.sh      # once
#   bash deploy/cloudrun/deploy.sh     # every time
#   bash deploy/cloudrun/deploy.sh --no-build   # redeploy the last built images
# Access (private: IAM-gated, only the invoker below):
#   gcloud run services proxy tender-demo --region us-central1 --port 8080
#   open http://localhost:8080
# Data: GCS bucket mounted at /data (projects, OCR cache, reports, inbox); the
# LangGraph SQLite checkpoint works on local disk (GRAPH_DB_SCRATCH_DIR) and is
# copied to the bucket after every job — SQLite on a FUSE mount is unsafe.
# Models: Gemini 2.5 Flash on Vertex AI (text + OCR) with the service account's
# credentials — no API key anywhere in the cloud. Synthetic documents only.
set -euo pipefail
cd "$(dirname "$0")/../.."

PROJECT=${PROJECT:-$(gcloud config get-value project 2>/dev/null)}
REGION=${REGION:-us-central1}
SERVICE=${SERVICE:-tender-demo}
REPO_NAME=${REPO:-tender}
BUCKET=${BUCKET:-${PROJECT}-data}
SA_EMAIL="${SA:-tender-run}@${PROJECT}.iam.gserviceaccount.com"
SECRET=${SECRET:-tender-api-key}
TAG=${TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)}
REPO="${REGION}-docker.pkg.dev/${PROJECT}/${REPO_NAME}"
VERTEX="https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${REGION}/endpoints/openapi"
MODEL=${MODEL:-google/gemini-2.5-flash}
INVOKER=${INVOKER:-$(gcloud config get-value account 2>/dev/null)}

if [ "${1:-}" != "--no-build" ]; then
    echo "== Cloud Build: three linux/amd64 images tagged $TAG"
    gcloud builds submit --config deploy/cloudrun/cloudbuild.yaml \
        --substitutions "_REPO=${REPO},_TAG=${TAG}" --project "$PROJECT" --quiet .
else
    TAG=${TAG_OVERRIDE:-latest}
fi

echo "== Deploy $SERVICE ($REGION), images :$TAG"
gcloud run deploy "$SERVICE" --region "$REGION" --project "$PROJECT" --quiet \
    --service-account "$SA_EMAIL" \
    --no-allow-unauthenticated \
    --no-cpu-throttling --min-instances 0 --max-instances 1 --concurrency 20 \
    --timeout 3600 --session-affinity \
    --add-volume "name=data,type=cloud-storage,bucket=${BUCKET}" \
    --container proxy --image "${REPO}/proxy:${TAG}" --port 8080 \
        --cpu 1 --memory 256Mi --depends-on backend,frontend \
    --container backend --image "${REPO}/backend:${TAG}" --cpu 1 --memory 2Gi \
        --set-env-vars "^|^DATA_DIR=/data|INBOX_DIR=/data/inbox|GRAPH_DB_SCRATCH_DIR=/tmp/graph|GITHUB_MODELS_BASE_URL=${VERTEX}|TEXT_MODEL=${MODEL}|VISION_MODEL=${MODEL}|TEXT_MODEL_FALLBACKS=|VISION_MODEL_FALLBACKS=|MAX_PARALLEL_BIDS=${MAX_PARALLEL_BIDS:-4}" \
        --set-secrets "API_KEY=${SECRET}:latest" \
        --add-volume-mount "volume=data,mount-path=/data" \
        --startup-probe "httpGet.path=/health,httpGet.port=8000,initialDelaySeconds=2,periodSeconds=3,timeoutSeconds=3,failureThreshold=40" \
    --container frontend --image "${REPO}/frontend:${TAG}" --cpu 1 --memory 1Gi \
        --set-env-vars "BACKEND_URL=http://127.0.0.1:8000,PUBLIC_BACKEND_URL=/api,STREAMLIT_SERVER_ENABLE_CORS=false,STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false" \
        --set-secrets "API_KEY=${SECRET}:latest" \
        --startup-probe "tcpSocket.port=8501,initialDelaySeconds=2,periodSeconds=3,failureThreshold=40"

echo "== Invoker: $INVOKER"
gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" --project "$PROJECT" \
    --member "user:${INVOKER}" --role roles/run.invoker --quiet >/dev/null
URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format "value(status.url)")
echo "deployed: $URL (IAM-gated)"
echo "open it:  gcloud run services proxy $SERVICE --region $REGION --port 8080   ->  http://localhost:8080"
