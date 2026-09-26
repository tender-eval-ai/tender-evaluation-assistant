#!/usr/bin/env bash
# Deploy the app at one image tag: bash deploy/azure/deploy.sh <tag>
#
# The deploy-azure workflow runs this after pushing the images, with the names in its
# environment. From a laptop (az and gh logged in) it reads them from the repository
# variables setup.sh stored. OPENAI_MODEL / OPENAI_MODEL_VERSION pick another model when
# the region doesn't offer the default.
set -euo pipefail
cd "$(dirname "$0")/../.."

TAG=${1:?usage: deploy.sh <image tag, e.g. a commit SHA the workflow pushed>}
REPO=${REPO:-chenyufang-data/tender-evaluation-assistant}
setting() {  # the environment's value, else the repository variable
    local value=${!1:-}
    [ -n "$value" ] || value=$(gh variable get "$1" -R "$REPO")
    printf '%s' "$value"
}
RG=$(setting AZURE_RESOURCE_GROUP)
PARAMS=(suffix="$(setting AZURE_NAME_SUFFIX)" prefix="$(setting AZURE_PREFIX)" imageTag="$TAG"
        ghcrUser="$(setting AZURE_GHCR_USER)" signInClientId="$(setting AZURE_SIGNIN_CLIENT_ID)")
[ -z "${OPENAI_MODEL:-}" ] || PARAMS+=(openAiModel="$OPENAI_MODEL")
[ -z "${OPENAI_MODEL_VERSION:-}" ] || PARAMS+=(openAiModelVersion="$OPENAI_MODEL_VERSION")

URL=$(az deployment group create -g "$RG" -n "app-${TAG:0:12}" -f deploy/azure/main.bicep \
    -p "${PARAMS[@]}" --query properties.outputs.appUrl.value -o tsv)
echo "deployed ${TAG:0:12}: $URL (Entra ID sign-in, assigned users only)"
