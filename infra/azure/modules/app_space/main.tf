# app_space — one Project Console space (staging OR prod).
#
# Provisions: a Linux App Service Plan, a containerized Linux Web App, a USER-ASSIGNED managed
# identity, a Key Vault holding this space's secrets, an App Service **Hybrid Connection** to the
# on-prem SQL Server (no VPN), and the role grants + app settings that turn the one env-driven
# image into THIS environment.
#
# Why a user-assigned identity (not system-assigned): the app must have Key Vault read access
# BEFORE it starts, so its @Microsoft.KeyVault(...) settings resolve on first boot. A
# system-assigned identity only exists *after* the app is created, which would force a
# create-app → grant-role → app-reads-secret cycle (and a failed first boot). A user-assigned
# identity is created first, granted AcrPull + Key Vault read, then handed to the app — no cycle.
#
# On-prem SQL reach: the Hybrid Connection tunnels TCP to sql_host:sql_port through Azure Relay.
# An on-prem Hybrid Connection Manager (HCM) agent dials OUT to Relay on 443 — no inbound firewall
# change. The app's connection strings use exactly "sql_host,sql_port" so the traffic matches the
# hybrid connection endpoint. ETO + Reporting share the server, so this one endpoint serves both.

terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
    random  = { source = "hashicorp/random", version = "~> 3.5" }
  }
}

data "azurerm_client_config" "current" {}

# Short, globally-unique-ish Key Vault name (KV names are 3-24 chars, alphanumeric + hyphens).
resource "random_string" "kv" {
  length  = 6
  upper   = false
  special = false
}

locals {
  kv_name = "kv-pc-${var.env}-${random_string.kv.result}"  # e.g. kv-pc-prod-a1b2c3
  # pyodbc "host,port" form — used for BOTH the Reporting store and the ETO source (same server),
  # and it must equal the hybrid connection endpoint so the app routes through the tunnel.
  sql_server = "${var.sql_host},${var.sql_port}"
}

# ── identity (created first, so role grants precede the app) ─────────────────────
resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${var.app_name}"
  resource_group_name = var.resource_group_name
  location            = var.location
  tags                = var.tags
}

# ── this space's secret store ────────────────────────────────────────────────────
resource "azurerm_key_vault" "this" {
  name                       = local.kv_name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  enable_rbac_authorization  = true  # RBAC, not legacy access policies
  purge_protection_enabled   = true
  soft_delete_retention_days = 7
  tags                       = var.tags
}

resource "azurerm_role_assignment" "kv_admin" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = var.kv_admin_object_id
}

resource "azurerm_role_assignment" "kv_read" {
  scope                = azurerm_key_vault.this.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# ── secrets (values from sensitive Terraform vars; need admin role to write) ──────
resource "azurerm_key_vault_secret" "secret_key" {
  name         = "CONSOLE-SECRET-KEY"
  value        = var.secret_key
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.kv_admin]
}

resource "azurerm_key_vault_secret" "store_user" {
  name         = "CONSOLE-STORE-USER"
  value        = var.store_user
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.kv_admin]
}

resource "azurerm_key_vault_secret" "store_pwd" {
  name         = "CONSOLE-STORE-PWD"
  value        = var.store_pwd
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.kv_admin]
}

resource "azurerm_key_vault_secret" "eto_user" {
  name         = "ETO-USER"
  value        = var.eto_user
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.kv_admin]
}

resource "azurerm_key_vault_secret" "eto_pwd" {
  name         = "ETO-PWD"
  value        = var.eto_pwd
  key_vault_id = azurerm_key_vault.this.id
  depends_on   = [azurerm_role_assignment.kv_admin]
}

# ── Hybrid Connection: the app's private path to the on-prem SQL Server ───────────
# A named channel in the shared Relay namespace...
resource "azurerm_relay_hybrid_connection" "sql" {
  name                         = "hc-${var.app_name}-sql"
  resource_group_name          = var.resource_group_name
  relay_namespace_name         = var.relay_namespace_name
  requires_client_authorization = true
  user_metadata                = "SQL Server for Project Console ${var.env} (${local.sql_server})"
}

# ...linked to THIS app with the concrete endpoint. On-prem, add this same connection in HCM and
# point it at the SQL host:port so the tunnel completes.
resource "azurerm_web_app_hybrid_connection" "sql" {
  web_app_id = azurerm_linux_web_app.this.id
  relay_id   = azurerm_relay_hybrid_connection.sql.id
  hostname   = var.sql_host
  port       = var.sql_port
}

# ── compute ──────────────────────────────────────────────────────────────────────
resource "azurerm_service_plan" "this" {
  name                = "plan-${var.app_name}"
  resource_group_name = var.resource_group_name
  location            = var.location
  os_type             = "Linux"
  sku_name            = var.plan_sku
  tags                = var.tags
}

# ── the app ──────────────────────────────────────────────────────────────────────
resource "azurerm_linux_web_app" "this" {
  name                = var.app_name
  resource_group_name = var.resource_group_name
  location            = var.location
  service_plan_id     = azurerm_service_plan.this.id
  https_only          = true
  tags                = var.tags

  # Use the user-assigned identity for everything, and tell App Service to resolve Key Vault
  # references with it too (defaults to system-assigned otherwise).
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }
  key_vault_reference_identity_id = azurerm_user_assigned_identity.app.id

  site_config {
    # Pull the image from the shared ACR using the user-assigned identity (no admin creds).
    container_registry_use_managed_identity       = true
    container_registry_managed_identity_client_id = azurerm_user_assigned_identity.app.client_id
    application_stack {
      docker_registry_url = "https://${var.acr_login_server}"
      docker_image_name   = "${var.image_name}:${var.image_tag}"
    }
    ftps_state    = "Disabled"
    http2_enabled = true
  }

  app_settings = merge(
    {
      # App Service must know which port the container listens on.
      "WEBSITES_PORT" = "8000"
      "CONSOLE_PORT"  = "8000"

      # App Service terminates TLS and reaches the container over the bridge network, so the
      # app MUST bind 0.0.0.0 — but we still want secure cookies + HSTS, which key off
      # CONSOLE_HTTPS=1. The CONSOLE_BIND_HOST override (added in serve_console.py) keeps the
      # bind at 0.0.0.0 even with CONSOLE_HTTPS=1. Both are needed together here.
      "CONSOLE_BIND_HOST" = "0.0.0.0"
      "CONSOLE_HTTPS"     = "1"

      # env-driven config — this is what makes the shared image "staging" vs "prod"
      "CONSOLE_TENANT"  = var.console_tenant
      "CONSOLE_ENV"     = var.env
      "CONSOLE_THREADS" = tostring(var.console_threads)
      "CONSOLE_AUTH"    = var.console_auth

      # database targets. Server = the hybrid connection endpoint (host,port) for BOTH the
      # Reporting store and the read-only ETO source (same on-prem server, different DB).
      "CONSOLE_STORE_SERVER" = local.sql_server
      "CONSOLE_STORE_DB"     = var.store_db
      "CONSOLE_ETO_SERVER"   = local.sql_server

      # secrets — Key Vault references; App Service resolves them via the user-assigned identity
      "CONSOLE_SECRET_KEY" = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.secret_key.id})"
      "CONSOLE_STORE_USER" = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.store_user.id})"
      "CONSOLE_STORE_PWD"  = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.store_pwd.id})"
      "ETO_USER"           = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.eto_user.id})"
      "ETO_PWD"            = "@Microsoft.KeyVault(SecretUri=${azurerm_key_vault_secret.eto_pwd.id})"
    },
    # LDAP settings only when actually using the LDAP backend (interim; needs a DC reachable —
    # add a second Hybrid Connection for the DC on TCP 389 if you go this route).
    var.console_auth == "ldap" ? {
      "CONSOLE_LDAP_SERVER" = var.ldap_server
      "CONSOLE_AD_DOMAIN"   = var.ad_domain
      "CONSOLE_AD_NETBIOS"  = var.ad_netbios
    } : {}
  )

  # Grants + secrets must exist before the app boots so its Key Vault references resolve and the
  # image pull is authorized on first start. (No cycle: these depend on the identity, not the app.)
  depends_on = [
    azurerm_role_assignment.kv_read,
    azurerm_role_assignment.acr_pull,
  ]
}
