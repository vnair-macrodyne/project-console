variable "env" {
  description = "Environment name: staging | prod. Becomes CONSOLE_ENV and tags the resources."
  type        = string
}

variable "app_name" {
  description = "Web App name (globally unique), e.g. project-console-staging."
  type        = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "tags" {
  type    = map(string)
  default = {}
}

variable "plan_sku" {
  description = "App Service Plan SKU (Linux), e.g. B1 (staging) or P0v3 (prod)."
  type        = string
}

# ── image ──
variable "acr_login_server" {
  type = string
}

variable "acr_id" {
  description = "Resource id of the shared ACR (for the AcrPull role grant)."
  type        = string
}

variable "image_name" {
  type = string
}

variable "image_tag" {
  type = string
}

# ── runtime config ──
variable "console_tenant" {
  type = string
}

variable "console_auth" {
  type = string
}

variable "console_threads" {
  type = number
}

variable "store_db" {
  description = "Reporting database name for this env."
  type        = string
}

# ── on-prem SQL reach (Hybrid Connection endpoint; also the pyodbc host,port) ──
variable "relay_namespace_name" {
  description = "Name of the shared Azure Relay namespace to create the hybrid connection in."
  type        = string
}

variable "sql_host" {
  description = "On-prem SQL Server hostname (no instance suffix)."
  type        = string
}

variable "sql_port" {
  description = "Static TCP port of the on-prem SQL Server."
  type        = number
}

# ── secrets (stored in this space's Key Vault) ──
variable "secret_key" {
  type      = string
  sensitive = true
}

variable "store_user" {
  type      = string
  sensitive = true
}

variable "store_pwd" {
  type      = string
  sensitive = true
}

variable "eto_user" {
  type      = string
  sensitive = true
}

variable "eto_pwd" {
  type      = string
  sensitive = true
}

# ── Entra SSO (only consumed when console_auth = entra) ──
variable "entra_tenant_id" {
  type    = string
  default = ""
}

variable "entra_client_id" {
  type    = string
  default = ""
}

variable "entra_client_secret" {
  type      = string
  default   = ""
  sensitive = true
}

variable "entra_slo" {
  description = "Single-logout: also end the Entra session on /logout (CONSOLE_ENTRA_SLO)."
  type        = bool
  default     = false
}

# ── LDAP (only consumed when console_auth = ldap) ──
variable "ldap_server" {
  type    = string
  default = ""
}

variable "ad_domain" {
  type    = string
  default = ""
}

variable "ad_netbios" {
  type    = string
  default = ""
}

variable "kv_admin_object_id" {
  description = "Entra object id granted Key Vault Secrets Officer on this space's vault."
  type        = string
}
