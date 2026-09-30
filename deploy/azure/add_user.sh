#!/usr/bin/env bash
# Let one more person sign in to the demo, and with --contributor also deploy it:
#   bash deploy/azure/add_user.sh <email> [--contributor]
# Invites the address as a guest of this directory (the same person is returned if they
# were invited before), assigns them to the sign-in app registration, and with
# --contributor grants Contributor on the demo's resource group. No key vault access:
# the secrets stay readable by the app's identity only.
set -euo pipefail
# A failed command stops the script (set -e); this says where, since a failure inside
# $(...) can otherwise stop it without a word.
# $? is read first: the $(basename) below would reset it to 0.
trap 'rc=$?; echo "$(basename "$0") stopped at line $LINENO (exit $rc)" >&2' ERR
EMAIL=${1:?usage: add_user.sh <email> [--contributor]}
REPO=${REPO:-tender-eval-ai/tender-evaluation-assistant}
RG=$(gh variable get AZURE_RESOURCE_GROUP -R "$REPO")
PREFIX=$(gh variable get AZURE_PREFIX -R "$REPO")
SIGNIN_ID=$(gh variable get AZURE_SIGNIN_CLIENT_ID -R "$REPO")
GRAPH=https://graph.microsoft.com/v1.0

FQDN=$(az containerapp show -g "$RG" -n "${PREFIX}-demo" --query properties.configuration.ingress.fqdn -o tsv)
USER_ID=$(az rest --method POST --uri "$GRAPH/invitations" --query invitedUser.id -o tsv --body \
    "{\"invitedUserEmailAddress\":\"$EMAIL\",\"inviteRedirectUrl\":\"https://$FQDN\",\"sendInvitationMessage\":true}")
SIGNIN_SP=$(az ad sp show --id "$SIGNIN_ID" --query id -o tsv)
[ -n "$(az rest --method GET --uri "$GRAPH/servicePrincipals/$SIGNIN_SP/appRoleAssignedTo" \
    --query "value[?principalId=='$USER_ID'].id" -o tsv)" ] ||
    az rest --method POST --uri "$GRAPH/servicePrincipals/$SIGNIN_SP/appRoleAssignedTo" -o none --body \
        "{\"principalId\":\"$USER_ID\",\"resourceId\":\"$SIGNIN_SP\",\"appRoleId\":\"00000000-0000-0000-0000-000000000000\"}"
echo "$EMAIL can sign in at https://$FQDN (after accepting the invitation e-mail)"

if [ "${2:-}" = "--contributor" ]; then
    az role assignment create --assignee-object-id "$USER_ID" --assignee-principal-type User \
        --role Contributor --scope "$(az group show -n "$RG" --query id -o tsv)" -o none
    echo "$EMAIL is Contributor on $RG"
fi
