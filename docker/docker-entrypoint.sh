#!/usr/bin/env bash
# Project Console container entrypoint.
#
# Fails fast on the handful of settings that, if missing, would let the app *start* but then
# misbehave in ways that are painful to diagnose — an unset secret key silently rotating
# sessions on every restart, or SQL-auth creds absent on a Linux image where Windows/Trusted
# auth cannot work. Then it hands off to the CMD (waitress via serve_console.py) with `exec`
# so signals reach the server and the container stops cleanly.
set -euo pipefail

fail() { echo "ENTRYPOINT ERROR: $*" >&2; exit 1; }

DEMO="$(printf '%s' "${CONSOLE_DEMO:-}" | tr '[:upper:]' '[:lower:]')"
is_demo() { [[ "$DEMO" == "1" || "$DEMO" == "true" || "$DEMO" == "yes" ]]; }

if ! is_demo; then
  # A stable secret key is required: without it Flask generates a random one per process,
  # so every restart (and every scaled-out instance) invalidates all sessions.
  [[ -n "${CONSOLE_SECRET_KEY:-}" ]] || fail \
    "CONSOLE_SECRET_KEY is not set. Generate one and pass it in:  python -c 'import secrets;print(secrets.token_hex(32))'"

  # Windows/Trusted DB auth cannot work in a Linux container — require SQL-auth creds for
  # both stores. (Azure phase: swap the Reporting store to managed identity here.)
  [[ "${CONSOLE_STORE_TRUSTED:-}" == "1" ]] && fail \
    "CONSOLE_STORE_TRUSTED=1 is a Windows-only (domain-joined) mode and cannot work in this Linux container. Use CONSOLE_STORE_USER/CONSOLE_STORE_PWD instead."
  [[ -n "${CONSOLE_STORE_USER:-}" && -n "${CONSOLE_STORE_PWD:-}" ]] || fail \
    "CONSOLE_STORE_USER / CONSOLE_STORE_PWD must be set (SQL auth to the Reporting store)."
  [[ -n "${ETO_USER:-}" && -n "${ETO_PWD:-}" ]] || fail \
    "ETO_USER / ETO_PWD must be set (SQL auth to the read-only ETO database)."

  # On-prem this image authenticates people via the LDAP bind (pywin32 is absent on Linux,
  # so the Windows LogonUser path is unavailable). Warn — don't hard-fail — if the LDAP
  # target is unset, since the Entra/Azure phase will replace this backend entirely.
  AUTH="$(printf '%s' "${CONSOLE_AUTH:-}" | tr '[:upper:]' '[:lower:]')"
  if [[ "$AUTH" == "windows" ]]; then
    fail "CONSOLE_AUTH=windows needs pywin32, which is not installed on this Linux image. Set CONSOLE_AUTH=ldap (on-prem) or the Entra backend (Azure)."
  fi
  if [[ "$AUTH" != "entra" ]]; then
    if [[ -z "${CONSOLE_LDAP_SERVER:-}" || -z "${CONSOLE_AD_DOMAIN:-}" ]]; then
      echo "ENTRYPOINT WARNING: CONSOLE_AUTH=ldap but CONSOLE_LDAP_SERVER / CONSOLE_AD_DOMAIN are not both set — login will fail until they are." >&2
    fi
  fi
fi

echo "Project Console container: tenant=${CONSOLE_TENANT:-<default>} env=${CONSOLE_ENV:-prod} auth=${CONSOLE_AUTH:-ldap} demo=${DEMO:-0} port=${CONSOLE_PORT:-8000}"
exec "$@"
