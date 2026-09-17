# tender-review: project AWS infrastructure (shared)

Terraform for everything **inside** the project account `tender-review-dev`: today the private
synthetic-data bucket; later the network, database, containers and app deployment. Both
collaborators run it with their own `dev-admin` sign-in. It needs **no access** to the company
account (the company): the account, sign-in roles and budgets are created there separately by the
account owner.

```
infra/
├── bootstrap/            run once: state bucket inside tender-review-dev
├── dev/                  resources in tender-review-dev (synthetic bucket today)
├── backend.hcl.example   copy to backend.hcl after bootstrap
└── README.md
```

## Before the first run

1. The account owner has applied the company layer and sent you:
   - the **`project_handover`** values (account ID, bucket name)
   - the **`cli_profiles`** block
2. Sign-in (once per laptop):
   ```bash
   aws configure sso
   #   SSO session name: tender · start URL: https://<your-sso-id>.awsapps.com/start
   #   SSO region: <Identity Center region> · pick account tender-review-dev · role DevAdmin
   #   profile name: dev-admin
   # (or paste the cli_profiles block into ~/.aws/config)
   aws sso login --sso-session tender
   aws sts get-caller-identity --profile dev-admin     # must show the tender-review-dev account ID
   ```

## First run (one person, once)

```bash
cd infra

cd bootstrap
cp terraform.tfvars.example terraform.tfvars      # account_id, region, state bucket name
terraform init && terraform apply
cd ..
cp backend.hcl.example backend.hcl                # bucket = state_bucket output

cd dev
cp terraform.tfvars.example terraform.tfvars      # values from project_handover
terraform init -backend-config=../backend.hcl
terraform plan -out=tfplan
terraform apply tfplan
```

The second person only needs `backend.hcl` and `dev/terraform.tfvars` (same values), then
`terraform init -backend-config=../backend.hcl` and `terraform plan` shows "No changes".

**Check access as a normal user:**
```bash
aws s3 ls --profile dev-synthetic
aws s3 ls s3://tender-review-dev-synthetic/ --profile dev-synthetic   # README.md
```

## Updating as we go

Every infrastructure change is a normal PR:

```bash
git switch -c infra/<what-changes>
# edit dev/*.tf
terraform fmt -recursive
cd dev && terraform validate
terraform plan -out=tfplan        # paste the plan summary into the PR
# the other person reviews the code and the plan, then:
terraform apply tfplan
git push                          # merge the PR
```

- State is shared and locked in the project account, so only one person can apply at a time.
- Don't change these resources in the console; `terraform plan` will show it as drift.
- Import something made by hand with an `import { to = … id = … }` block, then plan and apply.
- Things the company layer controls (who has access, role permissions, new accounts, budgets)
  are requested from the account owner, not changed here.

**Needs a company-layer change first:** a new bucket that DevSyntheticData should reach, or a new
role (e.g. a CI deploy role via GitHub OIDC can be created *here* in the project account, but a new
Identity Center permission set can't).

## Later: deploying the app from CI

Add a GitHub Actions OIDC identity provider and a deploy role in `dev/` (this account). The
workflow assumes that role with no stored keys and runs `terraform apply` / container deploys,
still without any access to the company.

Safety nets: `allowed_account_ids` (refuses any account but tender-review-dev), `prevent_destroy`
on buckets, versioned and locked state. Never commit `terraform.tfvars`, `backend.hcl` or state.
Commit `.terraform.lock.hcl`.
