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


def test_the_hosted_demo_takes_synthetic_cases_only():
    """The gateway already keeps a confidential project's text off Azure OpenAI; HOSTED_DEMO
    also keeps its files off Azure: synthetic projects only, and no uploads."""
    assert "{ name: 'HOSTED_DEMO', value: '1' }" in MAIN


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


def test_the_scripts_say_where_they_stopped_and_setup_prepares_a_new_subscription():
    """setup.sh once stopped without a word: under pipefail, `tr </dev/urandom | head` fails
    with a broken pipe inside $(...). Every script now reports the line it stopped at, and
    setup.sh registers the resource providers a new subscription lacks."""
    setup = (ROOT / "deploy/azure/setup.sh").read_text()
    for name in ("setup.sh", "deploy.sh", "add_user.sh"):
        # $? is saved before $(basename) resets it, so the exit code isn't always 0.
        assert "trap 'rc=$?; echo \"$(basename \"$0\") stopped at line $LINENO (exit $rc)" in (ROOT / "deploy/azure" / name).read_text(), name
    assert "tr -dc" not in setup and "openssl rand -hex 3" in setup
    for provider in ("Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.DBforPostgreSQL", "Microsoft.CognitiveServices",
                     "Microsoft.KeyVault", "Microsoft.Storage", "Microsoft.ManagedIdentity"):
        assert provider in setup, provider


def test_the_model_can_live_in_another_region_and_every_deploy_says_which():
    """canadacentral listed gpt-4.1-mini as GlobalStandard and then refused to deploy it
    (2026-09-30): the OpenAI resource alone moves, and the region setup.sh chose reaches every
    later deploy, or the workflow would try to move the resource back."""
    setup = (ROOT / "deploy/azure/setup.sh").read_text()
    deploy = (ROOT / "deploy/azure/deploy.sh").read_text()
    workflow = (ROOT / ".github/workflows/deploy-azure.yml").read_text()
    assert "param openAiLocation string = location" in MAIN and "location: openAiLocation" in MAIN
    assert 'openAiLocation="$OPENAI_LOCATION"' in setup
    for name in ("AZURE_OPENAI_LOCATION", "AZURE_OPENAI_MODEL", "AZURE_OPENAI_MODEL_VERSION"):
        assert f'"{name}=' in setup, name
        assert f"optional {name}" in deploy, name
        assert f"{name}: ${{{{ vars.{name} }}}}" in workflow, name


def test_the_default_model_has_a_price_so_the_budget_can_stop_it():
    """app.llm.usage has no Azure prices: without MODEL_PRICES every call cost $0 and
    LLM_DAILY_BUDGET_USD could never trip (found with a live call, 2026-09-30)."""
    import json
    model = re.search(r"param openAiModel string = '([^']+)'", MAIN).group(1)
    prices = json.loads(re.search(r"param modelPricesJson string = '(.+)'", MAIN).group(1))
    assert {"in", "out"} <= set(prices[model]), model
