output "app_url" {
  description = "Default HTTPS URL of the app."
  value       = "https://${azurerm_linux_web_app.this.default_hostname}"
}

output "identity_principal_id" {
  description = "User-assigned managed identity principal id (AcrPull + Key Vault Secrets User)."
  value       = azurerm_user_assigned_identity.app.principal_id
}

output "key_vault_name" {
  description = "This space's Key Vault name."
  value       = azurerm_key_vault.this.name
}

output "hybrid_connection_name" {
  description = "Relay hybrid connection to add in the on-prem Hybrid Connection Manager (HCM)."
  value       = azurerm_relay_hybrid_connection.sql.name
}

output "sql_endpoint" {
  description = "The on-prem SQL endpoint the hybrid connection routes to (host,port)."
  value       = local.sql_server
}
