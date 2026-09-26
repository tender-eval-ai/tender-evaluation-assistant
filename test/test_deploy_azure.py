"""The Azure demo's template keeps the settings that hold its cost and its exposure down,
and runs the worker exactly as compose does. CI also compiles the template itself (the
deploy-azure workflow); these tests read it as text, so they need no Azure tools."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "deploy/azure/main.bicep").read_text()
POSTGRES = (ROOT / "deploy/azure/postgres.bicep").read_text()


def test_the_worker_runs_the_pipelines_compose_runs():
    compose = (ROOT / "docker-compose.yml").read_text()
    in_compose = re.search(r'"--pipelines", "([^"]+)"', compose).group(1)
    in_template = re.search(r"var pipelines = '([^']+)'", MAIN).group(1)
    assert in_template == in_compose


def test_nothing_is_public_without_sign_in():
    assert "external: !empty(signInClientId)" in MAIN, "nginx adds the API key: no sign-in, no public ingress"
    assert "unauthenticatedClientAction: 'RedirectToLoginPage'" in MAIN
    assert "allowInsecure: false" in MAIN


def test_the_app_scales_to_zero_and_to_one_replica_at_most():
    assert "minReplicas: 0" in MAIN, "an always-on replica runs far past the free grant"
    assert "maxReplicas: 1" in MAIN, "one writer on the file share"


def test_only_the_free_database_tier_and_pay_per_token_models():
    assert "name: 'Standard_B1ms'" in POSTGRES and "tier: 'Burstable'" in POSTGRES
    allowed = re.search(r"@allowed\(\[([^\]]+)\]\)\s*param openAiSku", MAIN).group(1)
    assert "Provisioned" not in allowed


def test_secrets_come_from_the_key_vault_not_the_template():
    for name in ("api-key", "database-url", "ghcr-token", "sign-in-secret"):
        assert f"keyVaultUrl: '${{vaultSecret}}/{name}', identity: identity.id" in MAIN, name
    assert "vault.getSecret('postgres-password')" in MAIN
    assert "@secure()" in POSTGRES
