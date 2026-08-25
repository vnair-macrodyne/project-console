# Project Console — Azure infrastructure (staging + prod).
#
# Two fully separate App Services from ONE container image. The image is the env-driven build
# from the repo Dockerfile; staging vs prod is nothing but a different CONSOLE_ENV + config, so
# both App Services pull the SAME image tag from one shared Azure Container Registry (ACR) and
# differ only in their app settings and (optionally) their plan size.
#
#   staging  -> app: <prefix>-staging   CONSOLE_ENV=staging  -> Reporting DB Macrodyne_Reporting_Staging
#   prod     -> app: <prefix>-prod      CONSOLE_ENV=prod     -> Reporting DB Macrodyne_Reporting
#
# On-prem SQL reach: NO VPN / ExpressRoute. Each space uses an App Service **Hybrid Connection**
# (Azure Relay) to reach the on-prem SQL Server host:port. An on-prem Hybrid Connection Manager
# (HCM) agent dials OUT to Azure Relay on 443 — no inbound firewall change. ETO + both Reporting
# DBs live on the one server, so one endpoint (sql_host:sql_port) per space covers all of them.
#
# Layout:
#   main.tf              provider, resource group, shared ACR, shared Relay namespace, two spaces
#   variables.tf         inputs (region, image, SKUs, SQL host/port, per-env DB + secrets, auth)
#   outputs.tf           app URLs, ACR login server, relay namespace, identity principal ids
#   modules/app_space/   one reusable space (plan + web app + key vault + hybrid connection)
#
# Prereqs: an Azure subscription, the `az` CLI logged in (`az login`), Terraform >= 1.5, and a
# static TCP port on the on-prem SQL Server (Hybrid Connections need host:PORT, not a named
# instance). Secrets are NOT committed — see terraform.tfvars.example and README.md.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
  # Remote state (state holds secret values). Config is supplied at init time from backend.hcl
  # (gitignored) so the globally-unique storage account name isn't hardcoded here:
  #   terraform init -backend-config=backend.hcl
  # Run bootstrap-state.sh first to create the storage account. See DEPLOY_AZURE_RUNBOOK.md.
  backend "azurerm" {}
}

provider "azurerm" {
  features {}
  # subscription_id can be set here or via ARM_SUBSCRIPTION_ID / `az account set`.
  subscription_id = var.subscription_id != "" ? var.subscription_id : null
}

# ── Resource group holding everything ────────────────────────────────────────────
resource "azurerm_resource_group" "console" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

# ── Shared container registry — both spaces pull the same image from here ─────────
resource "azurerm_container_registry" "acr" {
  name                = var.acr_name
  resource_group_name = azurerm_resource_group.console.name
  location            = azurerm_resource_group.console.location
  sku                 = "Basic"
  admin_enabled       = false # apps pull via managed identity + AcrPull, not the admin user
  tags                = var.tags
}

# ── Shared Azure Relay namespace — holds each space's Hybrid Connection ───────────
# One namespace; each space creates its own hybrid connection inside it (below, in the module).
resource "azurerm_relay_namespace" "console" {
  name                = var.relay_namespace_name
  resource_group_name = azurerm_resource_group.console.name
  location            = azurerm_resource_group.console.location
  sku_name            = "Standard" # Relay namespaces are Standard tier
  tags                = var.tags
}

# ── The two spaces ───────────────────────────────────────────────────────────────
# Same module, invoked twice. Everything that differs between staging and prod is passed in.

module "staging" {
  source = "./modules/app_space"

  env                 = "staging"
  app_name            = "${var.app_name_prefix}-staging"
  resource_group_name = azurerm_resource_group.console.name
  location            = azurerm_resource_group.console.location
  tags                = var.tags

  # compute
  plan_sku = var.staging_plan_sku

  # image (shared ACR + the tag to run)
  acr_login_server = azurerm_container_registry.acr.login_server
  acr_id           = azurerm_container_registry.acr.id
  image_name       = var.image_name
  image_tag        = var.staging_image_tag

  # tenant / runtime config
  console_tenant  = var.console_tenant
  console_auth    = var.console_auth
  console_threads = var.console_threads

  # on-prem SQL reach — Hybrid Connection to this host:port (ETO + Reporting share the server)
  relay_namespace_name = azurerm_relay_namespace.console.name
  sql_host             = var.sql_host
  sql_port             = var.sql_port
  store_db             = var.staging_store_db

  # secrets for this env (kept in this space's Key Vault, referenced by the app)
  secret_key = var.staging_secret_key
  store_user = var.staging_store_user
  store_pwd  = var.staging_store_pwd
  eto_user   = var.eto_user
  eto_pwd    = var.eto_pwd

  # Entra SSO (only applied when console_auth = entra)
  entra_tenant_id     = var.entra_tenant_id
  entra_client_id     = var.entra_client_id
  entra_client_secret = var.entra_client_secret
  entra_slo           = var.entra_slo

  # LDAP (interim, only if the app reaches an on-prem DC — see README on preferring Entra)
  ldap_server = var.ldap_server
  ad_domain   = var.ad_domain
  ad_netbios  = var.ad_netbios

  # who may administer secrets in this space's Key Vault (object id of you / a group)
  kv_admin_object_id = var.kv_admin_object_id
}

module "prod" {
  source = "./modules/app_space"

  env                 = "prod"
  app_name            = "${var.app_name_prefix}-prod"
  resource_group_name = azurerm_resource_group.console.name
  location            = azurerm_resource_group.console.location
  tags                = var.tags

  plan_sku = var.prod_plan_sku

  acr_login_server = azurerm_container_registry.acr.login_server
  acr_id           = azurerm_container_registry.acr.id
  image_name       = var.image_name
  image_tag        = var.prod_image_tag

  console_tenant  = var.console_tenant
  console_auth    = var.console_auth
  console_threads = var.console_threads

  relay_namespace_name = azurerm_relay_namespace.console.name
  sql_host             = var.sql_host
  sql_port             = var.sql_port
  store_db             = var.prod_store_db

  secret_key = var.prod_secret_key
  store_user = var.prod_store_user
  store_pwd  = var.prod_store_pwd
  eto_user   = var.eto_user
  eto_pwd    = var.eto_pwd

  entra_tenant_id     = var.entra_tenant_id
  entra_client_id     = var.entra_client_id
  entra_client_secret = var.entra_client_secret
  entra_slo           = var.entra_slo

  ldap_server = var.ldap_server
  ad_domain   = var.ad_domain
  ad_netbios  = var.ad_netbios

  kv_admin_object_id = var.kv_admin_object_id
}
