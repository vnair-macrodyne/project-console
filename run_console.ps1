# run_console.ps1 — start Project Console under waitress on MACRO-ETO-SVR.
#
# Non-secret settings live here. SECRETS (passwords, secret key) are NOT in this file — it goes
# into git. Put them in a local, UNTRACKED console_secrets.ps1 next to this script, e.g.:
#
#     $env:CONSOLE_SECRET_KEY = "a-fixed-random-string"
#     $env:CONSOLE_STORE_USER = "MacrodyneConsoleSvc"; $env:CONSOLE_STORE_PWD = "..."
#     $env:ETO_USER = "TotalETOReportWriter";          $env:ETO_PWD = "..."
#
# and add  console_secrets.ps1  to .gitignore. (Or set those as machine env vars instead.)
#
# HTTPS: waitress can't terminate TLS, so with CONSOLE_HTTPS=1 we bind LOCALHOST only and let
# Caddy hold the cert on :443 and reverse-proxy here. Set CONSOLE_HTTPS=0 to serve plain HTTP on
# the LAN (0.0.0.0:8000) with no Caddy.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# ---- non-secret config ----
$env:CONSOLE_TENANT    = "tenant_macrodyne.json"
$env:CONSOLE_AD_DOMAIN = "macrodynepress.com"   # UPN suffix — users log in as user@this
# Auth: 'windows' uses the OS to validate the AD password (pywin32 LogonUser) — no LDAP server or
# cert needed on a domain-joined box. Requires:  pip install pywin32
# Alternative: set CONSOLE_AUTH="ldap" + CONSOLE_LDAP_SERVER="<a-DC-hostname>" and, for NTLM,
# CONSOLE_AD_NETBIOS="MACR0DYNE" (the auto-guess "MACRODYNE" is wrong — note the zero).
$env:CONSOLE_AUTH      = "windows"
if (-not $env:CONSOLE_HTTPS) { $env:CONSOLE_HTTPS = "1" }   # 1 = behind Caddy TLS; 0 = plain HTTP

# ---- secrets ----
$secrets = Join-Path $PSScriptRoot "console_secrets.ps1"
if (Test-Path $secrets) { . $secrets }

$required = @("CONSOLE_SECRET_KEY","CONSOLE_STORE_USER","CONSOLE_STORE_PWD","ETO_USER","ETO_PWD")
$missing  = $required | Where-Object { -not (Test-Path "Env:$_") }
if ($missing) {
    Write-Host "Missing required env vars: $($missing -join ', ')" -ForegroundColor Yellow
    Write-Host "Create console_secrets.ps1 (untracked) that sets them, then re-run." -ForegroundColor Yellow
    exit 1
}

# ---- launch ----
# serve_console.py reads the env we just set (CONSOLE_HTTPS picks 127.0.0.1 vs 0.0.0.0) and starts
# waitress. Using a .py launcher avoids PowerShell mis-parsing an inline `python -c "..."`.
Write-Host "Starting Project Console  (CONSOLE_HTTPS=$($env:CONSOLE_HTTPS), CONSOLE_AUTH=$($env:CONSOLE_AUTH))" -ForegroundColor Green
python serve_console.py
