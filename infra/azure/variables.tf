# Root inputs. Fill non-secret values in terraform.tfvars; pass secrets via a gitignored
# *.auto.tfvars, environment variables (TF_VAR_*), or your CI secret store — never commit them.

variable "subscription_id" {
  description = "Azure subscription id. Leave blank to use ARM_SUBSCRIPTION_ID / the az CLI's current account."
  type        = string
  default     = ""
}

variable "resource_group_name" {
  description = "Resource group that holds the ACR, Relay namespace and both App Services."
  type        = string
  default     = "rg-project-console"
}

variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "canadacentral"
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default = {
    application = "project-console"
    managed_by  = "terraform"
  }
}

variable "app_name_prefix" {
  description = "Prefix for the two web apps; '-staging'/'-prod' are appended. Must be globally unique."
  type        = string
  default     = "project-console"
}

# ── container registry / image ───────────────────────────────────────────────────
variable "acr_name" {
  description = "Globally-unique ACR name (5-50 alphanumerics, no hyphens)."
  type        = string
  default     = "acrprojectconsole"
}

variable "image_name" {
  description = "Repository/name of the image inside the ACR (e.g. project-console)."
  type        = string
  default     = "project-console"
}

variable "staging_image_tag" {
  description = "Image tag staging runs. Deploy a new build to staging by bumping this."
  type        = string
  default     = "staging"
}

variable "prod_image_tag" {
  description = "Image tag prod runs. Promote by setting this to the tag staging has validated."
  type        = string
  default     = "prod"
}

# ── Azure Relay (Hybrid Connections) ─────────────────────────────────────────────
variable "relay_namespace_name" {
  description = "Globally-unique Azure Relay namespace name (holds each space's Hybrid Connection)."
  type        = string
  default     = "relay-project-console"
}

# ── on-prem SQL reach (via Hybrid Connection) ────────────────────────────────────
# ETO (Macrodyne_Production) and both Reporting DBs live on the SAME server, so one endpoint
# serves everything. Hybrid Connections need a STATIC TCP port — give SQLEXPRESS a fixed port
# (e.g. 1433) rather than relying on the SQL Browser / named-instance dynamic port.
variable "sql_host" {
  description = "On-prem SQL Server hostname as the app + Hybrid Connection will use it (e.g. MACRO-ETO-SVR). No instance suffix — the static port is set separately."
  type        = string
}

variable "sql_port" {
  description = "Static TCP port the on-prem SQL Server listens on."
  type        = number
  default     = 1433
}

# ── plan sizing (staging smaller than prod) ──────────────────────────────────────
variable "staging_plan_sku" {
  description = "App Service Plan SKU for staging (Linux). B1 supports Hybrid Connections (5/plan)."
  type        = string
  default     = "B1"
}

variable "prod_plan_sku" {
  description = "App Service Plan SKU for prod (Linux). P0v3 for production; B-series also works if load is light."
  type        = string
  default     = "P0v3"
}

# ── shared runtime config ────────────────────────────────────────────────────────
variable "console_tenant" {
  description = "CONSOLE_TENANT profile filename baked into the image."
  type        = string
  default     = "tenant_macrodyne.json"
}

variable "console_auth" {
  description = <<-EOT
    CONSOLE_AUTH backend. The Azure target is 'entra' (pending the OIDC backend in auth.py) —
    with Entra the app needs NO on-prem reach for login. 'ldap' is a stopgap and only works if
    the app can reach a DC on TCP 389 (add a second Hybrid Connection for the DC if you go this
    route). Both spaces share this until you split them.
  EOT
  type    = string
  default = "ldap"
}

variable "console_threads" {
  description = "waitress worker threads (CONSOLE_THREADS)."
  type        = number
  default     = 8
}

# ── ETO read-only SQL login (same server as Reporting, database Macrodyne_Production) ──
variable "eto_user" {
  description = "ETO read-only SQL login."
  type        = string
  sensitive   = true
}

variable "eto_pwd" {
  description = "ETO read-only SQL password."
  type        = string
  sensitive   = true
}

# ── per-env Reporting database names (same server, different DB) ──────────────────
variable "staging_store_db" {
  description = "Reporting database name for staging."
  type        = string
  default     = "Macrodyne_Reporting_Staging"
}

variable "prod_store_db" {
  description = "Reporting database name for prod."
  type        = string
  default     = "Macrodyne_Reporting"
}

# ── per-env secrets ──────────────────────────────────────────────────────────────
variable "staging_secret_key" {
  description = "Flask CONSOLE_SECRET_KEY for staging (fixed 64-hex string)."
  type        = string
  sensitive   = true
}

variable "prod_secret_key" {
  description = "Flask CONSOLE_SECRET_KEY for prod (fixed 64-hex string, DIFFERENT from staging)."
  type        = string
  sensitive   = true
}

variable "staging_store_user" {
  description = "Reporting-store SQL login for staging (write on the Console DB only)."
  type        = string
  sensitive   = true
}

variable "staging_store_pwd" {
  description = "Reporting-store SQL password for staging."
  type        = string
  sensitive   = true
}

variable "prod_store_user" {
  description = "Reporting-store SQL login for prod."
  type        = string
  sensitive   = true
}

variable "prod_store_pwd" {
  description = "Reporting-store SQL password for prod."
  type        = string
  sensitive   = true
}

# ── Entra SSO (only used when console_auth = entra) ──────────────────────────────
# One app registration can serve both spaces — register BOTH callback URLs on it (see the
# staging_callback_url / prod_callback_url outputs after apply).
variable "entra_tenant_id" {
  description = "Entra tenant (directory) id."
  type        = string
  default     = ""
}

variable "entra_client_id" {
  description = "App registration's application (client) id."
  type        = string
  default     = ""
}

variable "entra_client_secret" {
  description = "A client secret on the app registration (stored in each space's Key Vault)."
  type        = string
  default     = ""
  sensitive   = true
}

variable "entra_slo" {
  description = "Single-logout: also end the Entra session on /logout."
  type        = bool
  default     = false
}

# ── LDAP (interim, optional — only used when console_auth = ldap) ─────────────────
variable "ldap_server" {
  description = "DC hostname reachable from the app (CONSOLE_LDAP_SERVER). Blank if using Entra."
  type        = string
  default     = ""
}

variable "ad_domain" {
  description = "UPN suffix, e.g. macrodynepress.com (CONSOLE_AD_DOMAIN)."
  type        = string
  default     = ""
}

variable "ad_netbios" {
  description = "NETBIOS short domain for the NTLM bind (CONSOLE_AD_NETBIOS), e.g. MACR0DYNE."
  type        = string
  default     = ""
}

# ── Key Vault administration ──────────────────────────────────────────────────────
variable "kv_admin_object_id" {
  description = <<-EOT
    Entra object id (user or group) granted Key Vault Secrets Officer on both spaces' vaults so
    you can read/rotate secrets. Get yours with:  az ad signed-in-user show --query id -o tsv
  EOT
  type = string
}
