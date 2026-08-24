# Deploying Project Console as a container

One image, two homes. The same `project-console` image runs **on-prem today** (LDAP
form-login against the DC, SQL-auth to the ETO and Reporting databases) and, in a later
phase, on **Azure App Service with Entra ID SSO**. Nothing environment-specific is baked
in — everything that differs is an environment variable. This is the vehicle for the move
off the ETO server: we containerize now, keep serving the on-prem build, and add the Entra
backend when Azure is ready, without a second codebase.

This sits alongside the two existing runbooks: `DEPLOY_SERVER.md` (bare-metal on
MACRO-ETO-SVR behind Caddy) and `DEPLOY_LOCAL.md` (dev laptop). Nothing in those changes —
the container is an additional way to run the *same* app.

## Files

| File | Purpose |
|------|---------|
| `Dockerfile` | `python:3.12-slim` + ODBC Driver 17 (the version pinned in `connections.py`) + deps + app. |
| `.dockerignore` | Keeps `.git`, `.env`, `__pycache__`, diagnostics, `sql/`, docs and outputs out of the image. |
| `docker/docker-entrypoint.sh` | Fails fast on missing secret key / DB creds; warns on unset LDAP; then `exec`s waitress. |
| `.env.docker.example` | The full list of runtime settings. Copy to `.env.docker` and fill in. |
| `docker-compose.yml` | Local/on-prem run: build, publish 8000, healthcheck. |

## Why LDAP on-prem (not Windows auth)

The bare-metal deploy uses `CONSOLE_AUTH=windows` — pywin32's `LogonUser` asks the
domain-joined OS to validate the typed password. A Linux container is **not** domain-joined
and has no pywin32 (its requirement is marked `platform_system == "Windows"`, so it is
skipped on this image). So the container authenticates the same people the same way they
type their credentials, but by **binding to a domain controller** over LDAP instead:

- `CONSOLE_AUTH=ldap`
- `CONSOLE_LDAP_SERVER` — a DC hostname the container can reach on port **389**
- NTLM bind by default → **no LDAPS certificate needed**, password never crosses the wire
  in cleartext
- `CONSOLE_AD_DOMAIN=macrodynepress.com` (UPN suffix) and
  `CONSOLE_AD_NETBIOS=MACR0DYNE` (note the zero — the auto-guess is wrong)

**Prerequisite before this can go live on-prem:** the container host must be able to reach a
DC on 389 (NTLM). That is the practical substitute for the domain-joined LogonUser path. If
389 is closed but LDAPS (636) is available with a valid DC cert, set
`CONSOLE_LDAP_METHOD=simple` + `CONSOLE_LDAP_SSL=1` instead.

## Reaching SQL Server from the container

The ETO and Reporting databases live on `MACRO-ETO-SVR\SQLEXPRESS` — a **named instance**.
Two things the container needs that a domain-joined host got for free:

1. **Name resolution.** The container host must resolve `MACRO-ETO-SVR`. If DNS inside the
   container doesn't, add a host mapping (`extra_hosts:` in compose, or `--add-host`).
2. **Named-instance port.** `\SQLEXPRESS` uses a dynamic port that clients discover via the
   **SQL Browser (UDP 1434)**. If that isn't reachable from the container, give SQLEXPRESS a
   **static TCP port** and connect by `host,port`:
   `CONSOLE_STORE_SERVER=MACRO-ETO-SVR,1433` (and the ETO server likewise if separate).

Both stores use **SQL auth** in the container (Trusted/Windows auth can't work on Linux):
`CONSOLE_STORE_USER/PWD` (write on the Console DB only) and `ETO_USER/PWD` (read-only).

## Build & run

```bash
# from the repo root
cp .env.docker.example .env.docker      # fill in CONSOLE_SECRET_KEY, DB creds, LDAP
docker build -t project-console:latest .
docker run --env-file .env.docker -p 8000:8000 project-console:latest
# or:
docker compose up -d --build
```

Put TLS in front (Caddy/NGINX/platform) exactly as today; the container serves plain HTTP on
0.0.0.0:8000. Set `CONSOLE_HTTPS=1` only to turn on secure-cookie hardening once it's behind
TLS — waitress itself never terminates TLS. Health: `GET /login` (used by the built-in
HEALTHCHECK).

## What is intentionally NOT in the image

`sql/` migrations and the `console_diag_*` probes are excluded — migrations are applied by
hand in SSMS by the DB owner (e.g. `sql/013_item_price_ref.sql` + its GRANT), and the probes
aren't part of the served app. The nightly batch jobs (`console_seed_itemprice.py`,
`console_sync.py`) **are** in the image and can be run as one-off container commands
(`docker run ... python console_seed_itemprice.py`) or lifted to a scheduled task later.

## The Azure / Entra seam (next phase)

The move to Entra is a change in **one place** — `console_web/auth.py` — plus env:

- Add an `entra` backend to `authenticate()` (OIDC against Entra ID); the roles lookup in
  `Reporting.tblConsoleUser` and the `viewer < pm < admin` gates are unchanged.
- `CONSOLE_AUTH=entra` selects it; the LDAP env vars fall away.
- Reporting store → Azure SQL via **managed identity** (drop `CONSOLE_STORE_USER/PWD`);
  the swap lives behind `console.infra.connections.console_connection()`.
- ETO stays read-only over the site-to-site link, still SQL-auth.

The image does not change for any of that — only `auth.py` gains a backend and the env set
differs. That is the whole point of containerizing now: on-prem and Entra run from the same
build while the migration proceeds.
