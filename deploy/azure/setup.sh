#!/usr/bin/env bash
# One-time setup of the shared demo on Azure (checklist G4). Safe to re-run.
#
#   az login                       # the account that owns the subscription
#   gh auth login                  # to set the repository variables the deploy workflow reads
#   export GHCR_TOKEN=...          # a classic GitHub token with read:packages only
#   bash deploy/azure/setup.sh
#
# In resource group $RG it creates:
#   - the managed identity the app reads its secrets with, and a key vault (RBAC) holding
#     api-key, postgres-password, database-url, ghcr-token and sign-in-secret;
#   - everything in main.bicep except the app (a first pass), so the app's address is known;
#   - the Entra app registration for sign-in: only users assigned to it get in, and you are;
#   - the Entra app registration GitHub Actions deploys as: OIDC, no stored secret,
#     Contributor on this resource group only;
#   - the synthetic cases in the file share's inbox.
# Then it sets the repository variables and the azure-demo environment the workflow uses.
# No secret is printed or passed on a command line.
set -euo pipefail
# A failed command stops the script (set -e); this says where, since a failure inside
# $(...) can otherwise stop it without a word.
trap 'echo "$(basename "$0") stopped at line $LINENO (exit $?)" >&2' ERR
cd "$(dirname "$0")/../.."

REPO=${REPO:-tender-eval-ai/tender-evaluation-assistant}
RG=${RG:-tender-demo}
LOCATION=${LOCATION:-eastus2}
PREFIX=${PREFIX:-tender}
GHCR_USER=${GHCR_USER:-chenyufang-data}   # the account GHCR_TOKEN belongs to
: "${GHCR_TOKEN:?export GHCR_TOKEN: a classic GitHub token with the read:packages scope only}"

SUBSCRIPTION=$(az account show --query id -o tsv)
TENANT=$(az account show --query tenantId -o tsv)
ME=$(az ad signed-in-user show --query id -o tsv)

echo "== resource providers (a new subscription has none of these registered)"
for p in Microsoft.App Microsoft.OperationalInsights Microsoft.DBforPostgreSQL Microsoft.CognitiveServices \
         Microsoft.KeyVault Microsoft.Storage Microsoft.ManagedIdentity; do
    [ "$(az provider show -n "$p" --query registrationState -o tsv)" = Registered ] ||
        az provider register -n "$p" --wait -o none
done

# The suffix makes the global names unique; the repository variable keeps it stable.
SUFFIX=$(gh variable get AZURE_NAME_SUFFIX -R "$REPO" 2>/dev/null || true)
# openssl, not `tr </dev/urandom | head`: under pipefail, tr's broken pipe stopped the script.
[ -n "$SUFFIX" ] || SUFFIX=$(openssl rand -hex 3)
KV="${PREFIX}-kv-${SUFFIX}"
PG="${PREFIX}-pg-${SUFFIX}"
ID="${PREFIX}-id"

retry() { for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do "$@" && return 0; sleep 10; done; return 1; }
assign() {  # object id, role, scope, principal type
    [ -n "$(az role assignment list --assignee "$1" --role "$2" --scope "$3" --query "[0].id" -o tsv)" ] ||
        az role assignment create --assignee-object-id "$1" --assignee-principal-type "$4" \
            --role "$2" --scope "$3" -o none
}
has_secret() { az keyvault secret show --vault-name "$KV" -n "$1" -o none 2>/dev/null; }
put_secret() { printf '%s' "$2" | az keyvault secret set --vault-name "$KV" -n "$1" --file /dev/stdin -o none; }

echo "== resource group $RG ($LOCATION), subscription $SUBSCRIPTION"
az group create -n "$RG" -l "$LOCATION" -o none
RG_ID=$(az group show -n "$RG" --query id -o tsv)

echo "== managed identity $ID"
az identity show -g "$RG" -n "$ID" -o none 2>/dev/null || az identity create -g "$RG" -n "$ID" -o none
ID_PRINCIPAL=$(az identity show -g "$RG" -n "$ID" --query principalId -o tsv)

echo "== key vault $KV"
az keyvault show -n "$KV" -o none 2>/dev/null ||
    az keyvault create -g "$RG" -n "$KV" -l "$LOCATION" --enable-rbac-authorization true \
        --enabled-for-template-deployment true -o none
KV_ID=$(az keyvault show -n "$KV" --query id -o tsv)
assign "$ME" "Key Vault Secrets Officer" "$KV_ID" User
retry assign "$ID_PRINCIPAL" "Key Vault Secrets User" "$KV_ID" ServicePrincipal

echo "== secrets (generated here, never printed)"
if has_secret postgres-password; then
    PG_PASSWORD=$(az keyvault secret show --vault-name "$KV" -n postgres-password --query value -o tsv)
else
    PG_PASSWORD=$(openssl rand -hex 24)
    retry put_secret postgres-password "$PG_PASSWORD"   # the first write waits for the role to apply
fi
put_secret database-url "postgresql://tender:${PG_PASSWORD}@${PG}.postgres.database.azure.com:5432/tender?sslmode=require"
has_secret api-key || put_secret api-key "$(openssl rand -hex 24)"
put_secret ghcr-token "$GHCR_TOKEN"

echo "== first pass: everything but the app"
OUTPUTS=$(az deployment group create -g "$RG" -n infra -f deploy/azure/main.bicep \
    -p suffix="$SUFFIX" prefix="$PREFIX" imageTag=none ghcrUser="$GHCR_USER" deployApp=false \
    --query properties.outputs -o json)
output() { printf '%s' "$OUTPUTS" | python3 -c "import json,sys; print(json.load(sys.stdin)['$1']['value'])"; }
APP_URL="https://${PREFIX}-demo.$(output environmentDomain)"
STORAGE=$(output storageAccount)

echo "== sign-in app registration (assigned users only)"
SIGNIN_NAME="${PREFIX}-demo-signin"
SIGNIN_ID=$(az ad app list --display-name "$SIGNIN_NAME" --query "[0].appId" -o tsv)
[ -n "$SIGNIN_ID" ] || SIGNIN_ID=$(az ad app create --display-name "$SIGNIN_NAME" \
    --sign-in-audience AzureADMyOrg --query appId -o tsv)
az ad app update --id "$SIGNIN_ID" --web-redirect-uris "${APP_URL}/.auth/login/aad/callback" \
    --enable-id-token-issuance true --identifier-uris "api://${SIGNIN_ID}"
az ad sp show --id "$SIGNIN_ID" -o none 2>/dev/null || az ad sp create --id "$SIGNIN_ID" -o none
SIGNIN_SP=$(az ad sp show --id "$SIGNIN_ID" --query id -o tsv)
az ad sp update --id "$SIGNIN_SP" --set appRoleAssignmentRequired=true
GRAPH=https://graph.microsoft.com/v1.0
[ -n "$(az rest --method GET --uri "$GRAPH/servicePrincipals/$SIGNIN_SP/appRoleAssignedTo" \
    --query "value[?principalId=='$ME'].id" -o tsv)" ] ||
    az rest --method POST --uri "$GRAPH/servicePrincipals/$SIGNIN_SP/appRoleAssignedTo" -o none --body \
        "{\"principalId\":\"$ME\",\"resourceId\":\"$SIGNIN_SP\",\"appRoleId\":\"00000000-0000-0000-0000-000000000000\"}"
if ! has_secret sign-in-secret; then
    SIGNIN_SECRET=$(az ad app credential reset --id "$SIGNIN_ID" --append --display-name container-apps \
        --years 1 --query password -o tsv 2>/dev/null) || { echo "could not create the sign-in secret" >&2; exit 1; }
    put_secret sign-in-secret "$SIGNIN_SECRET"
    unset SIGNIN_SECRET
fi

echo "== GitHub Actions deploy identity (OIDC, Contributor on $RG only)"
GH_NAME="${PREFIX}-demo-github"
GH_APP=$(az ad app list --display-name "$GH_NAME" --query "[0].appId" -o tsv)
[ -n "$GH_APP" ] || GH_APP=$(az ad app create --display-name "$GH_NAME" --query appId -o tsv)
az ad sp show --id "$GH_APP" -o none 2>/dev/null || az ad sp create --id "$GH_APP" -o none
GH_SP=$(az ad sp show --id "$GH_APP" --query id -o tsv)
SUBJECT="repo:${REPO}:environment:azure-demo"
[ -n "$(az ad app federated-credential list --id "$GH_APP" --query "[?subject=='$SUBJECT'].name" -o tsv)" ] ||
    az ad app federated-credential create --id "$GH_APP" -o none --parameters \
        "{\"name\":\"azure-demo\",\"issuer\":\"https://token.actions.githubusercontent.com\",\"subject\":\"$SUBJECT\",\"audiences\":[\"api://AzureADTokenExchange\"]}"
retry assign "$GH_SP" Contributor "$RG_ID" ServicePrincipal

echo "== synthetic cases into the inbox (data/inbox on the file share)"
export AZURE_STORAGE_ACCOUNT="$STORAGE"
AZURE_STORAGE_KEY=$(az storage account keys list -g "$RG" -n "$STORAGE" --query "[0].value" -o tsv)
export AZURE_STORAGE_KEY
for case in test/data/synthetic_tender demo_case; do
    az storage file upload-batch --destination data --destination-path "inbox/$(basename "$case")" \
        --source "$case" --no-progress -o none
done
unset AZURE_STORAGE_KEY

echo "== repository variables and the azure-demo environment (ids, not secrets)"
gh api -X PUT "repos/$REPO/environments/azure-demo" >/dev/null
for pair in "AZURE_CLIENT_ID=$GH_APP" "AZURE_TENANT_ID=$TENANT" "AZURE_SUBSCRIPTION_ID=$SUBSCRIPTION" \
            "AZURE_RESOURCE_GROUP=$RG" "AZURE_NAME_SUFFIX=$SUFFIX" "AZURE_PREFIX=$PREFIX" \
            "AZURE_SIGNIN_CLIENT_ID=$SIGNIN_ID" "AZURE_GHCR_USER=$GHCR_USER"; do
    gh variable set "${pair%%=*}" -R "$REPO" --body "${pair#*=}"
done

echo
echo "Done. Next: run the deploy-azure workflow (Actions tab, Run workflow), then open"
echo "  $APP_URL"
echo "Let Nasi in: bash deploy/azure/add_user.sh <her email> --contributor"
