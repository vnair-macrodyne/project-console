# Project Console — Azure bring-up runbook

Ordered steps to stand up the two spaces (staging + prod) with **remote state**, **Entra SSO**,
in **Canada Central**. Runs on your Windows machine (Azure CLI, Terraform, Docker Desktop) — the
cloud sandbox has no Azure access. Commands work the same in PowerShell or Git Bash unless noted.

Legend: `⟨FILL⟩` = a value you supply. Anything under "secrets" never goes in git.

---

## Phase 0 — Prerequisites (once)

- **Tools**: `az` (Azure CLI), `terraform` >= 1.5, and **Docker Desktop** installed and running.
- **Azure permissions** on the target subscription:
  - **Owner** (or **Contributor** + **User Access Administrator**) — the Terraform creates *role
    assignments* (AcrPull, Key Vault roles), which Contributor alone can't do.
  - Rights to create an **Entra app registration** (Application Developer role or higher).
- Sign in and select the subscription:

```bash
az login
az account set --subscription "⟨SUBSCRIPTION_ID_OR_NAME⟩"
az account show --query "{sub:name, id:id, tenant:tenantId}" -o table
```

- Grab the two values Terraform needs from you:

```bash
az ad signed-in-user show --query id -o tsv        # -> kv_admin_object_id
az account show --query tenantId -o tsv             # -> entra_tenant_id
```

---

## Phase 1 — Remote state (once)

State holds secrets, so it lives in a locked storage account, created outside Terraform.

```bash
cd infra/azure
# Git Bash/WSL/Cloud Shell (it's a bash script). Storage name must be globally unique,
# 3-24 lowercase letters/digits. Change the suffix if 'sttfstateconsolemti' is taken.
./bootstrap-state.sh sttfstateconsolemti
```

Copy the four values it prints into **`backend.hcl`** (use `backend.hcl.example` as the template;
`backend.hcl` is gitignored).

> PowerShell (no bash)? Run these instead:
> ```powershell
> az group create -n rg-tfstate -l canadacentral
> az storage account create -n sttfstateconsolemti -g rg-tfstate -l canadacentral `
>   --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 --allow-blob-public-access false
> az storage account blob-service-properties update --account-name sttfstateconsolemti -g rg-tfstate --enable-versioning true
> az storage container create -n tfstate --account-name sttfstateconsolemti --auth-mode login
> ```

---

## Phase 2 — Entra app registration (once)

One app registration serves both spaces. The redirect URIs use the app names we set in tfvars
(`app_name_prefix` = `project-console-mti` ⇒ hosts `project-console-mti-staging/-prod`).

```bash
# create the app
APP_ID=$(az ad app create --display-name "Project Console" \
  --sign-in-audience AzureADMyOrg \
  --web-redirect-uris \
    "https://project-console-mti-staging.azurewebsites.net/auth/callback" \
    "https://project-console-mti-prod.azurewebsites.net/auth/callback" \
  --query appId -o tsv)
echo "entra_client_id = $APP_ID"

# create a client secret (copy the printed value — it won't be shown again)
az ad app credential reset --id "$APP_ID" --display-name "console-tf" --years 2 \
  --query password -o tsv
```

Keep `APP_ID` (→ `entra_client_id`) and the secret (→ `entra_client_secret`). If you change
`app_name_prefix`, update the redirect URIs to match.

---

## Phase 3 — Fill variables

```bash
cp terraform.tfvars.example terraform.tfvars
```

Edit **`terraform.tfvars`** (non-secrets). Confirm/adjust the globally-unique names and set:

```hcl
resource_group_name  = "rg-project-console"
location             = "canadacentral"
app_name_prefix      = "project-console-mti"       # -> project-console-mti-staging / -prod
acr_name             = "acrprojconsolemti"          # 5-50 alphanumerics, unique
relay_namespace_name = "relay-project-console-mti"  # unique

sql_host = "MACRO-ETO-SVR"      # as the app will resolve it via the hybrid connection
sql_port = 1433                 # the STATIC port you'll set on SQLEXPRESS (Phase 6)

console_auth       = "entra"
entra_tenant_id    = "⟨TENANT_ID⟩"
entra_client_id    = "⟨APP_ID from Phase 2⟩"
kv_admin_object_id = "⟨your object id⟩"
```

Create **`secrets.auto.tfvars`** (gitignored — never commit). Use the two **CONSOLE_SECRET_KEY**
values I gave you in chat:

```hcl
staging_secret_key  = "⟨staging key from chat⟩"
prod_secret_key     = "⟨prod key from chat⟩"
staging_store_user  = "MacrodyneConsoleSvcStg"
staging_store_pwd   = "⟨…⟩"
prod_store_user     = "MacrodyneConsoleSvc"
prod_store_pwd      = "⟨…⟩"
eto_user            = "TotalETOReportWriter"
eto_pwd             = "⟨…⟩"
entra_client_secret = "⟨client secret from Phase 2⟩"
```

---

## Phase 4 — Provision

```bash
terraform init -backend-config=backend.hcl
terraform plan -out tfplan          # review: 1 RG, ACR, relay ns, 2 plans, 2 apps, 2 KVs, 2 identities, role grants, secrets, 2 hybrid connections
terraform apply tfplan
```

If a name is taken, `apply` fails on that resource — change the name in `terraform.tfvars` (and the
Entra redirect URIs if the app prefix changed) and re-apply. When it finishes:

```bash
terraform output          # staging_url, prod_url, acr_login_server, hybrid connection names, callback URLs
```

---

## Phase 5 — Build & push the image

The apps are created but have no image yet. From the **repo root** (where the Dockerfile is), on a
machine with Docker Desktop:

```bash
ACR=$(terraform -chdir=infra/azure output -raw acr_login_server)
az acr login --name "${ACR%%.*}"
docker build -t "$ACR/project-console:staging" .
docker push "$ACR/project-console:staging"
# promote the SAME image to prod (no rebuild):
docker tag  "$ACR/project-console:staging" "$ACR/project-console:prod"
docker push "$ACR/project-console:prod"

az webapp restart -g rg-project-console -n project-console-mti-staging
az webapp restart -g rg-project-console -n project-console-mti-prod
```

At this point the login page should load at `staging_url` — but reports won't work until SQL is
reachable (next phase).

---

## Phase 6 — On-prem: static SQL port + Hybrid Connection Manager

1. **Static SQL port.** In SQL Server Configuration Manager → SQL Server Network Configuration →
   Protocols for SQLEXPRESS → TCP/IP → IP Addresses → IPAll: set **TCP Port = 1433**, clear "TCP
   Dynamic Ports", restart the SQL service. (Match `sql_port` in tfvars.)
2. **Install HCM.** In the portal, open **project-console-mti-staging → Networking → Hybrid
   connections → Download connection manager**; install it on an on-prem Windows box that can reach
   SQL (the ETO server itself is fine). In HCM, **Add** the staging connection (it authenticates
   from the downloaded config). Repeat for **prod** (same download button on the prod app). HCM
   shows **Connected** once it can reach Relay (out, 443) and SQL `host:1433`.

> Only outbound **443** is needed from the on-prem box to Azure Relay — usually already open.

---

## Phase 7 — Verify

```bash
az webapp restart -g rg-project-console -n project-console-mti-staging
```

- Browse `staging_url` → you're redirected to **Entra sign-in** → back to the app.
  - First login: your Entra `preferred_username` (e.g. `you@macrodynepress.com`) is looked up in
    `Reporting.tblConsoleUser`. If you're not listed you'll come in as **viewer**. Seed yourself as
    admin in that table (by the username form it stores) if you need the /admin screen.
- Run a report → confirms the Hybrid Connection to SQL works.
- When staging looks right, prod is already running the same image; sanity-check `prod_url` too.

---

## Troubleshooting

- **`AuthorizationFailed` creating role assignments** → you lack Owner/User Access Administrator on
  the subscription. Ask whoever owns it to grant it or run the apply.
- **App shows a container/500 on first boot** → give the Key Vault role grants a minute to
  propagate, then `az webapp restart`. Check **Log stream** in the portal; the entrypoint prints why
  it refused (missing secret, etc.).
- **Report pages error but login works** → the Hybrid Connection isn't Connected, or SQL isn't on
  the static port. Check HCM status and that you can `telnet MACRO-ETO-SVR 1433` from the HCM box.
- **Entra loop / redirect mismatch** → the app's callback URL must exactly match a redirect URI on
  the app registration (`terraform output staging_callback_url` / `prod_callback_url`).
- **Name already taken** (ACR/relay/storage/app) → names are global; add/adjust the suffix and
  re-apply (and update the Entra redirect URIs if the app prefix changed).

---

## What's provisioned

Resource group `rg-project-console`: shared ACR + Relay namespace; per space a Linux App Service
Plan, a containerized Web App (user-assigned identity, image from ACR), a Key Vault (secrets +
`@Microsoft.KeyVault` references), and a Hybrid Connection to on-prem SQL. Rough run-rate ~$80/mo +
a few $/mo per hybrid connection listener. See README.md for the design and cost detail.
