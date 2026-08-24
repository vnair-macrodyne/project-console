output "acr_login_server" {
  description = "Registry to docker login / push the image to."
  value       = azurerm_container_registry.acr.login_server
}

output "relay_namespace" {
  description = "Azure Relay namespace holding the hybrid connections (used by the HCM download)."
  value       = azurerm_relay_namespace.console.name
}

output "staging_url" {
  description = "Staging App Service URL."
  value       = module.staging.app_url
}

output "prod_url" {
  description = "Prod App Service URL."
  value       = module.prod.app_url
}

output "staging_hybrid_connection" {
  description = "Staging hybrid connection name + SQL endpoint to configure in HCM."
  value       = "${module.staging.hybrid_connection_name} -> ${module.staging.sql_endpoint}"
}

output "prod_hybrid_connection" {
  description = "Prod hybrid connection name + SQL endpoint to configure in HCM."
  value       = "${module.prod.hybrid_connection_name} -> ${module.prod.sql_endpoint}"
}

output "staging_identity_principal_id" {
  description = "Staging web app managed identity (granted AcrPull + Key Vault get)."
  value       = module.staging.identity_principal_id
}

output "prod_identity_principal_id" {
  description = "Prod web app managed identity."
  value       = module.prod.identity_principal_id
}
