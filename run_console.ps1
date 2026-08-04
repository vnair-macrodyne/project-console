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

# ---- secrets / DB auth ----
$secrets = Join-Path $PSScriptRoot "console_secrets.ps1"
if (Test-Path $secrets) { . $secrets }

# Database auth: default to WINDOWS auth (CONSOLE_STORE_TRUSTED=1) — the app connects to both
# Macrodyne_Reporting and Macrodyne_Production as the account it runs under (no SQL passwords).
# That account must have access to both DBs. To use SQL logins instead, set CONSOLE_STORE_USER/PWD
# and ETO_USER/PWD (in console_secrets.ps1) — then this leaves trusted off.
if (-not $env:CONSOLE_STORE_USER) { $env:CONSOLE_STORE_TRUSTED = "1" }

if (-not $env:CONSOLE_SECRET_KEY) {
    Write-Host "CONSOLE_SECRET_KEY is not set. Put a fixed random string in console_secrets.ps1:" -ForegroundColor Yellow
    Write-Host '    $env:CONSOLE_SECRET_KEY = "…"   (generate: python -c ""import secrets;print(secrets.token_hex(32))"")' -ForegroundColor Yellow
    exit 1
}
$dbmode = if ($env:CONSOLE_STORE_TRUSTED -eq "1") { "Windows auth (Trusted)" } else { "SQL auth ($($env:CONSOLE_STORE_USER))" }
Write-Host "Database auth: $dbmode" -ForegroundColor Green

# ---- launch ----
# serve_console.py reads the env we just set (CONSOLE_HTTPS picks 127.0.0.1 vs 0.0.0.0) and starts
# waitress. Using a .py launcher avoids PowerShell mis-parsing an inline `python -c "..."`.
Write-Host "Starting Project Console  (CONSOLE_HTTPS=$($env:CONSOLE_HTTPS), CONSOLE_AUTH=$($env:CONSOLE_AUTH))" -ForegroundColor Green
python serve_console.py
