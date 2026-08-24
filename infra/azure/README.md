# Project Console on Azure — two spaces (staging + prod)

Terraform that stands up **two fully separate App Services** — `project-console-staging` and
`project-console-prod` — running the **same** env-driven container image from **one shared Azure
Container Registry**. Staging vs prod is nothing but a different `CONSOLE_ENV` and config, so the
only real differences are each space's app settings, secrets, and (optionally) plan size.

On-prem SQL is reached with **App Service Hybrid Connections** — **no VPN, no ExpressRoute**. An
on-prem agent dials *out* to Azure on 443, so there's typically no firewall change at all.

```
rg-project-console
├── acrprojectconsole            (shared registry — both apps pull from here)
├── relay-project-console        (shared Azure Relay namespace — holds the hybrid connections)
├── plan-project-console-staging (B1)   → project-console-staging   CONSOLE_ENV=staging
│                                          → Key Vault kv-pc-staging-xxxxxx
│                                          → hybrid conn hc-...-staging-sql → SQL host:port
└── plan-project-console-prod    (P0v3)  → project-console-prod      CONSOLE_ENV=prod
                                           → Key Vault kv-pc-prod-xxxxxx
                                           → hybrid conn hc-...-prod-sql → SQL host:port
```

Each space gets its own **user-assigned managed identity**, granted `AcrPull` on the registry and
`Key Vault Secrets User` on its own vault. Secrets (`CONSOLE_SECRET_KEY`, the SQL logins) live in
Key Vault and reach the app as `@Microsoft.KeyVault(...)` references — never plaintext in the portal.

## How the app reaches on-prem SQL (Hybrid Connections)

Instead of a VPN, each App Service has a **Hybrid Connection** to your SQL Server's `host:port`.
The path is:

```
App Service  ──▶  Azure Relay (443)  ◀──  HCM agent on-prem  ──▶  SQL Server host:port
```

- The **Hybrid Connection Manager (HCM)** runs on any on-prem Windows box that can reach SQL
  (the ETO server itself is fine). It makes an **outbound** connection to Azure Relay on **443** —
  no inbound port, no public IP, no VPN device.
- Because ETO (`Macrodyne_Production`) and both Reporting DBs are on the **one** server, a single
  endpoint (`sql_host:sql_port`) per space carries everything. The app's `CONSOLE_STORE_SERVER` and
  `CONSOLE_ETO_SERVER` are both set to exactly `sql_host,sql_port` so the traffic matches the tunnel.
- **Requirement:** a **static TCP port** on SQL. Hybrid Connections need a fixed `host:port` and
  can't use the SQL Browser / dynamic named-instance port. In SQL Server Configuration Manager, set
  a static TCP port for `SQLEXPRESS` (e.g. 1433) and connect by `host,port` (not `host\SQLEXPRESS`).
- Hybrid Connections are supported on **Basic and up** (Basic allows 5 per plan), so the B1/P0v3
  plans here are fine.

### Installing HCM on-prem (one-time)

After `terraform apply`:

1. In the Azure portal, open each App Service → **Networking → Hybrid connections**. You'll see the
   connection Terraform created (`terraform output staging_hybrid_connection` / `prod_...` names it).
2. Click **Download connection manager**, install HCM on the on-prem box, and **Add** each
   connection (it authenticates with the relay key automatically via the downloaded config).
3. HCM will show **Connected** once it can reach both Azure Relay (out, 443) and the SQL `host:port`.
   The apps then reach SQL transparently.

> LDAP note: if you run the interim `console_auth = "ldap"`, the DC must also be reachable — add a
> *second* Hybrid Connection for the DC on **TCP 389**. The cleaner path is **Entra SSO**
> (`console_auth = "entra"`), which needs no on-prem reach for login at all — see "Auth" below.

## What this depends on in the app

Two small, backward-compatible code changes ship alongside this (already in the repo):

- **`serve_console.py`** honours `CONSOLE_BIND_HOST`. App Service reaches the container over the
  bridge network, so the app must bind `0.0.0.0`; but we also set `CONSOLE_HTTPS=1` so the session
  cookie is `Secure` + HSTS is emitted. Without the override, `CONSOLE_HTTPS=1` alone would bind
  loopback and the platform could not reach the app. The Terraform sets both.
- **`console_config.py`** honours `CONSOLE_ETO_SERVER` / `CONSOLE_ETO_DB`. The ETO source address
  is now an app setting like the Reporting store already was. Unset on-prem → the profile default.

## Prerequisites

1. **Azure**: a subscription; `az login`; `az account set --subscription <id>` (or set
   `subscription_id`). Terraform >= 1.5, azurerm ~> 4.0.
2. **Static SQL port** on the on-prem server (see Hybrid Connections above).
3. **Image in the registry** (see next section).

## Build & push the image, then deploy

```bash
cd infra/azure
terraform init
cp terraform.tfvars.example terraform.tfvars      # fill non-secret values (incl. sql_host/sql_port)
#   put secrets in secrets.auto.tfvars (gitignored) or export TF_VAR_* — see the example file
terraform apply

# build the image (from the repo root, where the Dockerfile is) and push both tags
ACR=$(terraform -chdir=infra/azure output -raw acr_login_server)
az acr login --name "${ACR%%.*}"
docker build -t "$ACR/project-console:staging" .
docker push "$ACR/project-console:staging"
# promote the SAME image to prod by retagging (no rebuild):
docker tag  "$ACR/project-console:staging" "$ACR/project-console:prod"
docker push "$ACR/project-console:prod"

# apps pull on start/restart:
az webapp restart -g rg-project-console -n project-console-staging
az webapp restart -g rg-project-console -n project-console-prod
```

Then install HCM on-prem (above). `terraform output` prints `staging_url`, `prod_url`, and the
hybrid-connection names/endpoints.

## Promotion model

Staging and prod are decoupled by **image tag**. Build → push `:staging` → validate on the staging
URL → retag that exact image to `:prod` → restart prod. Because the image is identical and only
`CONSOLE_ENV`/config differ, what you tested is byte-for-byte what prod runs. (For immutable tags,
push `:<git-sha>` and set `staging_image_tag`/`prod_image_tag` to specific shas.)

## Secrets & state

- Secret values are set from Terraform variables → **Terraform state contains them**. Use a
  **remote backend** (uncomment the `backend "azurerm"` block in `main.tf`) so state lives in a
  locked storage account, not a local file. Never commit `*.tfstate` or `*.tfvars` (the `.gitignore`
  here enforces that; only `*.tfvars.example` is tracked).
- Rotate a secret by updating its value (in `secrets.auto.tfvars` / `TF_VAR_*`) and re-applying, or
  directly in Key Vault; then restart the app so it re-reads the reference.

## Auth: where Entra fits

`console_auth = "ldap"` is the interim setting and needs a DC reachable (a second Hybrid Connection
on TCP 389). The intended Azure end-state is **Entra SSO** (`console_auth = "entra"`), a new OIDC
backend in `console_web/auth.py` — not built yet. With Entra the app authenticates users in the
cloud and needs **no** on-prem reach for login; only the SQL hybrid connection remains. Flipping to
it is an app-setting change; no infrastructure here changes.

## Rough cost

~$80/month for the app tier (staging B1 ~$13, prod P0v3 ~$60–70, ACR Basic ~$5, Key Vaults ~$0–1),
plus a few dollars per Hybrid Connection listener (Azure Relay). No VPN gateway (~$140/mo) needed.
Confirm current figures in the Azure Pricing Calculator.

## Tearing down

`terraform destroy`. The Key Vaults have **purge protection on**, so their names stay reserved for
the soft-delete retention window (7 days) — pick fresh names if you recreate immediately.
