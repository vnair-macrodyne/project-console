#!/usr/bin/env bash
# One-time: create the Azure Storage account that holds Terraform remote state.
# Run this ONCE before the first `terraform init`. It is separate from the main Terraform
# (state can't store itself). Safe to re-run — every step is idempotent.
#
#   ./bootstrap-state.sh [storage_account_name]
#
# storage_account_name must be GLOBALLY UNIQUE, 3-24 lowercase letters/digits, no hyphens.
# After it runs, copy the printed values into backend.hcl, then:  terraform init -backend-config=backend.hcl
set -euo pipefail

LOCATION="${LOCATION:-canadacentral}"
STATE_RG="${STATE_RG:-rg-tfstate}"
CONTAINER="${CONTAINER:-tfstate}"
SA="${1:-${STATE_SA:-sttfstateconsolemti}}"   # <- change if this name is taken

echo "Subscription: $(az account show --query name -o tsv 2>/dev/null || echo '(run: az login)')"
echo "Creating state RG '$STATE_RG' in $LOCATION ..."
az group create -n "$STATE_RG" -l "$LOCATION" -o none

echo "Creating storage account '$SA' ..."
az storage account create -n "$SA" -g "$STATE_RG" -l "$LOCATION" \
  --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false -o none

echo "Enabling blob versioning (state history) ..."
az storage account blob-service-properties update \
  --account-name "$SA" -g "$STATE_RG" --enable-versioning true -o none

echo "Creating container '$CONTAINER' ..."
az storage container create -n "$CONTAINER" --account-name "$SA" --auth-mode login -o none

cat <<EOF

Done. Put this in  infra/azure/backend.hcl  (gitignored):

  resource_group_name  = "$STATE_RG"
  storage_account_name = "$SA"
  container_name       = "$CONTAINER"
  key                  = "project-console.tfstate"

Then:  terraform init -backend-config=backend.hcl
EOF
