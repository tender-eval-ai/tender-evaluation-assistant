#!/usr/bin/env bash
# Deploy the app at one image tag: bash deploy/azure/deploy.sh <tag>
#
# The deploy-azure workflow runs this after pushing the images, with the names in its
# environment. From a laptop (az and gh logged in) it reads them from the repository
# variables setup.sh stored. The Azure OpenAI region, model and version are optional: the
# template's defaults unless setup.sh stored others (or OPENAI_MODEL / OPENAI_MODEL_VERSION
# are set here).
set -euo pipefail
# A failed command stops the script (set -e); this says where, since a failure inside
# $(...) can otherwise stop it without a word.
# $? is read first: the $(basename) below would reset it to 0.
trap 'rc=$?; echo "$(basename "$0") stopped at line $LINENO (exit $rc)" >&2' ERR
cd "$(dirname "$0")/../.."

TAG=${1:?usage: deploy.sh <image tag, e.g. a commit SHA the workflow pushed>}
REPO=${REPO:-tender-eval-ai/tender-evaluation-assistant}
setting() {  # the environment's value, else the repository variable
    local value=${!1:-}
    [ -n "$value" ] || value=$(gh variable get "$1" -R "$REPO")
    printf '%s' "$value"
}
optional() {  # the same, but empty when neither is set
    local value=${!1:-}
    [ -n "$value" ] || value=$(gh variable get "$1" -R "$REPO" 2>/dev/null || true)
    printf '%s' "$value"
}
RG=$(setting AZURE_RESOURCE_GROUP)
PARAMS=(suffix="$(setting AZURE_NAME_SUFFIX)" prefix="$(setting AZURE_PREFIX)" imageTag="$TAG"
        ghcrUser="$(setting AZURE_GHCR_USER)" signInClientId="$(setting AZURE_SIGNIN_CLIENT_ID)")
OAI_LOCATION=$(optional AZURE_OPENAI_LOCATION)
OAI_MODEL=${OPENAI_MODEL:-$(optional AZURE_OPENAI_MODEL)}
OAI_VERSION=${OPENAI_MODEL_VERSION:-$(optional AZURE_OPENAI_MODEL_VERSION)}
[ -z "$OAI_LOCATION" ] || PARAMS+=(openAiLocation="$OAI_LOCATION")
[ -z "$OAI_MODEL" ] || PARAMS+=(openAiModel="$OAI_MODEL")
[ -z "$OAI_VERSION" ] || PARAMS+=(openAiModelVersion="$OAI_VERSION")
# A custom domain, once bound by hand (README: "A custom domain"), is declared on every deploy
# with its managed certificate; a deploy that left it out would remove the binding.
DOMAIN=$(optional AZURE_CUSTOM_DOMAIN)
if [ -n "$DOMAIN" ]; then
    CERT=$(az containerapp env certificate list -g "$RG" -n "$(setting AZURE_PREFIX)-env" --managed-certificates-only \
        --query "[?properties.subjectName=='$DOMAIN'].id | [0]" -o tsv)
    PARAMS+=(customDomain="$DOMAIN" customDomainCertificateId="$CERT")
fi

URL=$(az deployment group create -g "$RG" -n "app-${TAG:0:12}" -f deploy/azure/main.bicep \
    -p "${PARAMS[@]}" --query properties.outputs.appUrl.value -o tsv)
echo "deployed ${TAG:0:12}: $URL (Entra ID sign-in, assigned users only)"
