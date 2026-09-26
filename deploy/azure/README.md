# The shared demo on Azure

One private demo of the whole stack (checklist G4), on synthetic data only:

```
browser ─ Entra ID sign-in ─ Container Apps app (scales to zero, one replica at most)
                               ├─ web      nginx: the React UI; forwards the API and adds the key
                               ├─ api      FastAPI                        ┐ files on an Azure Files
                               └─ worker   the job queue (same image)     ┘ share at /data
                                              │                  │
                          Postgres Flexible Server B1ms     Azure OpenAI (through the gateway)
```

| File | What it does |
|---|---|
| `main.bicep`, `postgres.bicep` | Every resource except those `setup.sh` makes. Compiled on every pull request that touches this folder. |
| `setup.sh` | Run once from a laptop: the key vault and its secrets, the managed identity, the sign-in and deploy app registrations, a first pass of the template, the synthetic cases, and the repository variables. |
| `deploy.sh` | Deploys one image tag. The workflow runs it; it also works from a laptop. |
| `add_user.sh` | Lets one more person sign in, and with `--contributor` deploy. |
| `../../.github/workflows/deploy-azure.yml` | Run by hand: builds `backend` and `web`, pushes them to the GitHub Container Registry, and deploys through OIDC. |

## First time
1. **A subscription.** A Free Trial, made with a personal Microsoft account rather than a university one, so the demo outlives the university account. Start it when you're ready to deploy: the trial credit lasts 30 days.
2. **Tools:** `brew install azure-cli`, then `az login` and `gh auth login`.
3. **A token to pull the images:** a classic GitHub token with the `read:packages` scope only, in `GHCR_TOKEN`. It goes straight into the key vault.
4. Run `bash deploy/azure/setup.sh`. `LOCATION` (default `eastus2`) and `RG` (default `tender-demo`) can be set first.
5. Actions tab → **deploy-azure** → **Run workflow**. Then open the address `setup.sh` printed and sign in.
6. Let Nasi in: `bash deploy/azure/add_user.sh <email> --contributor`.

**If the first pass stops at the Azure OpenAI resource:** trial subscriptions have had limits on Azure OpenAI. Either upgrade to pay-as-you-go (the unused credit carries over), or pick a model the region offers (`az cognitiveservices model list -l <region>`) and rerun with `OPENAI_MODEL=… OPENAI_MODEL_VERSION=…`.

## What it costs
The trial credit covers the first 30 days. To keep the demo after that, upgrade to pay-as-you-go:
- **Postgres B1ms:** the free account covers 750 hours of B1ms and 32 GB a month for 12 months, which is the whole month. After that, it's the one real cost.
- **Container Apps:** the first 180,000 vCPU-seconds and 360,000 GiB-seconds a month are free, and a scaled-to-zero app costs nothing. Awake, the three containers take 2 vCPU and 4 GiB together, so the grant is about 25 hours awake a month.
- **Azure OpenAI:** pay per token; a pay-per-token deployment costs nothing idle.
- **Storage, the key vault and logs:** cents.

**The guardrails, and why each is in the template:**
- `minReplicas: 0`: an always-on replica would run far past the free grant.
- B1ms only: no other Postgres tier is free.
- `openAiSku` allows pay-per-token deployment types only, never provisioned throughput.
- `LLM_DAILY_BUDGET_USD` (default 2): the gateway stops model calls for a project past that amount a day.
- **Also set a budget alert** in Cost Management, for example $10 a month.

## Security
- **Nothing is reachable without sign-in.** The app gets public ingress only when a sign-in app registration is given. nginx adds the API key to every forwarded request, so whoever reaches the app can do anything the API can.
- **Only assigned users get in.** The sign-in registration requires assignment, and `setup.sh` and `add_user.sh` assign.
- **Secrets live in the key vault** and are read by the app's managed identity. The deploy identity is Contributor on the resource group only and holds no secret (OIDC). The Azure OpenAI key is a Container Apps secret that the template reads from the resource.
- **Postgres** has a public endpoint that requires TLS and accepts Azure services only; no client address is allowed in. A private network would need a VNet-integrated environment, which costs more.
- **Synthetic data only.** The gateway's policy lets a cloud endpoint see synthetic projects only. A redacted sample would need its host cleared in `LLM_CLEARED_HOSTS`, which this deployment doesn't set, and a confidential project never reaches a cloud endpoint.

## Taking it down
```bash
az group delete -n tender-demo --yes
az ad app delete --id "$(gh variable get AZURE_SIGNIN_CLIENT_ID)"
az ad app delete --id "$(gh variable get AZURE_CLIENT_ID)"
```
