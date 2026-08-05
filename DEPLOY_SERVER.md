# Project Console — Server Deployment & Run (MACRO‑ETO‑SVR)

**Scope:** deploying and running Project Console on **MACRO‑ETO‑SVR**, where users reach it. For a
developer laptop see `DEPLOY_LOCAL.md`.

**Topology**
```
  domain PCs ──HTTPS:443──►  Caddy (TLS)  ──HTTP─►  waitress 127.0.0.1:8000  ──►  console_web.app
                             MACRO-ETO-SVR                same host
```
- **App:** waitress serving `console_web.app:app` via `serve_console.py`.
- **TLS:** Caddy terminates HTTPS (waitress has no TLS of its own).
- **Databases** (`MACRO-ETO-SVR\SQLEXPRESS`): ETO `Macrodyne_Production` (read‑only, login
  `TotalETOReportWriter`); reporting store `Macrodyne_Reporting_Staging` for now (login
  `MacrodyneConsoleSvc`), moving to prod `Macrodyne_Reporting` once it's built out and the login is
  granted there.
- **Paths:** repo at `C:\reporting\project-console`.

---

## 1. One‑time setup

1. **Code:** clone/pull the repo to `C:\reporting\project-console`.
2. **Python 3.11+** on PATH; **ODBC Driver 17 for SQL Server** installed.
3. **Dependencies:**
   ```powershell
   pip install waitress pywin32 pyodbc cryptography
   pip install -r requirements.txt      # if present
   ```
4. **Secrets** — create `console_secrets.ps1` in the repo root (**not committed**; add to
   `.gitignore`). **Single‑quote** the passwords so a `$` isn't expanded:
   ```powershell
   # C:\reporting\project-console\console_secrets.ps1  — DO NOT COMMIT
   $env:CONSOLE_ENV        = 'staging'                     # store = Macrodyne_Reporting_Staging
   $env:CONSOLE_STORE_USER = 'MacrodyneConsoleSvc'; $env:CONSOLE_STORE_PWD = 'the$store$password'
   $env:ETO_USER           = 'TotalETOReportWriter';  $env:ETO_PWD         = 'the$eto$password'
   $env:CONSOLE_SECRET_KEY = 'a-fixed-random-string'      # generate once; keep constant forever
   ```
   Generate the key once: `python -c "import secrets; print(secrets.token_hex(32))"`.
   > Keep `CONSOLE_SECRET_KEY` **constant** across restarts — changing it logs everyone out.
5. **Auth:** `pip install pywin32` (already in step 3) enables Windows‑validated login — users sign
   in with their AD username + password, no LDAP server or certificate required.
6. **One‑time DB item:** run `console_seed_hourtype.py` once against the store to create/seed
   `Reporting.tlkpHourTypeDiscipline` (silences a benign startup warning). Read‑only otherwise.

---

## 2. Two run modes

### A) LAN test — plain HTTP (quick verification, no Caddy)

Binds `0.0.0.0:8000`, non‑Secure cookie so login works over `http://`.

```powershell
cd C:\reporting\project-console
. .\console_secrets.ps1
$env:CONSOLE_TENANT="tenant_macrodyne.json"; $env:CONSOLE_AUTH="windows"
$env:CONSOLE_AD_DOMAIN="macrodynepress.com"; $env:CONSOLE_HTTPS="0"
python serve_console.py
```
Startup line must read **`0.0.0.0:8000`**. Open the firewall once:
```powershell
New-NetFirewallRule -DisplayName "Project Console 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow -Profile Any
```
Browse from any domain PC: `http://MACRO-ETO-SVR:8000/`.

### B) Production — HTTPS behind Caddy

Binds `127.0.0.1:8000` (localhost only) with a Secure cookie + HSTS; Caddy holds the cert on 443.

**b1. One‑time cert → PEM (no openssl needed).** Export the AD‑CA cert to
`C:\Caddy\certs\console.pfx` (certlm.msc → the cert → All Tasks → Export → *Yes, export the private
key* → PFX → set a password), then:
```powershell
pip install cryptography
python pfx_to_pem.py C:\Caddy\certs\console.pfx C:\Caddy\certs    # writes console.crt + console.key
```

**b2. Caddyfile** — `C:\Caddy\Caddyfile`:
```
MACRO-ETO-SVR.MACR0DYNE.local {
    tls C:\Caddy\certs\console.crt C:\Caddy\certs\console.key
    encode zstd gzip
    reverse_proxy 127.0.0.1:8000
}
```

**b3. Start the app (HTTPS mode) then Caddy:**
```powershell
cd C:\reporting\project-console
. .\console_secrets.ps1
$env:CONSOLE_TENANT="tenant_macrodyne.json"; $env:CONSOLE_AUTH="windows"
$env:CONSOLE_AD_DOMAIN="macrodynepress.com"; $env:CONSOLE_HTTPS="1"
python serve_console.py
# in a second window:
C:\Caddy\caddy.exe run --config C:\Caddy\Caddyfile
```

**b4. Firewall/DNS:** open inbound **443** (and **80** for the HTTP→HTTPS redirect); **remove** the
8000 rule (waitress is localhost only now). The FQDN already resolves on the domain.
Users browse **`https://MACRO-ETO-SVR.MACR0DYNE.local/`** — clean padlock (domain PCs trust the AD CA).

---

## 3. Run as a Windows service (so it survives logoff/reboot)

Interactive `python serve_console.py` stops when the window closes. For production, run both as
services with **NSSM** (`nssm.exe`). Run the app service under an account that can reach the
databases (either keep the SQL logins in the env block, or a domain service account granted DB
access + `CONSOLE_STORE_TRUSTED=1`).

```powershell
# App (waitress via the launcher) — localhost, with its env
nssm install ProjectConsole "C:\Path\to\python.exe" "serve_console.py"
nssm set ProjectConsole AppDirectory "C:\reporting\project-console"
nssm set ProjectConsole AppEnvironmentExtra CONSOLE_HTTPS=1 CONSOLE_ENV=staging CONSOLE_TENANT=tenant_macrodyne.json CONSOLE_AUTH=windows CONSOLE_AD_DOMAIN=macrodynepress.com CONSOLE_SECRET_KEY=<fixed> CONSOLE_STORE_USER=MacrodyneConsoleSvc CONSOLE_STORE_PWD=<pwd> ETO_USER=TotalETOReportWriter ETO_PWD=<pwd>
nssm start ProjectConsole

# Caddy (TLS terminator)
nssm install ProjectConsoleTLS "C:\Caddy\caddy.exe" "run --config C:\Caddy\Caddyfile"
nssm set ProjectConsoleTLS AppDirectory "C:\Caddy"
nssm start ProjectConsoleTLS
```

---

## 4. Startup / Shutdown / Restart

| Action | Interactive (`python serve_console.py`) | Service (NSSM) |
|---|---|---|
| **Start** | run the block in §2 | `nssm start ProjectConsole` (+ `ProjectConsoleTLS`) |
| **Stop** | **Ctrl+C** in the window | `nssm stop ProjectConsole` (+ TLS) |
| **Restart after `git pull`** | Ctrl+C, then start again | `nssm restart ProjectConsole` |

> **Code changes require a restart.** A running process keeps executing the code it loaded at
> startup — `git pull` alone changes nothing until you restart the app process.

**Deploy an update:**
```powershell
cd C:\reporting\project-console
git pull
nssm restart ProjectConsole        # or Ctrl+C + start again if interactive
```

**Confirm the caching is live** after a restart: the log prints `built N ETO budgets …` **once**
per data change, not on every page load.

---

## 5. Cutover: staging store → prod store

When prod `Macrodyne_Reporting` is built out:
1. Create/populate its objects (run the `sql/00x` scripts + `console_seed_hourtype.py` against it).
2. In SSMS, grant `MacrodyneConsoleSvc` a **User Mapping** on `Macrodyne_Reporting`
   (`db_datareader` + `db_datawriter`, plus execute on the Reporting procs).
3. Remove `CONSOLE_ENV=staging` from `console_secrets.ps1` (or set
   `CONSOLE_STORE_DB=Macrodyne_Reporting`), and restart.

---

## 6. Troubleshooting (things we actually hit)

| Symptom | Cause / Fix |
|---|---|
| `waitress-serve : not recognized` | Use `python serve_console.py` (imports waitress) — not the exe on PATH. |
| PowerShell parse error on `python -c "…"` | Don't inline Python in PS; use `serve_console.py`. |
| `running scripts is disabled` | `powershell -ExecutionPolicy Bypass -File .\run_console.ps1`. |
| `LDAP not configured` at login | `pip install pywin32`; set `CONSOLE_AUTH=windows` + `CONSOLE_AD_DOMAIN`. |
| `Login failed 'MacrodyneConsoleSvc'` / `Cannot open database` (4060) | Pointed at prod `Macrodyne_Reporting` (no access). Use `CONSOLE_ENV=staging`. |
| `Login failed 'MACR0DYNE\Administrator'` under Trusted auth | That Windows account isn't granted on the SQLEXPRESS DBs. Use the SQL logins, or grant it in SSMS. |
| Password right but rejected | `$` in the password expanded — **single‑quote** it in `console_secrets.ps1`. |
| Works on the server, not from other PCs | Startup line says `127.0.0.1` (localhost). Set `CONSOLE_HTTPS=0` for the LAN test → `0.0.0.0`; and open firewall 8000. |
| Port unreachable from a laptop | Check on server `netstat -ano | findstr :8000` (want `0.0.0.0`), and from laptop `Test-NetConnection MACRO-ETO-SVR -Port 8000` (`TcpTestSucceeded: True`). Ping only proves the host is up, not the port. |
| Signed in, bounced to login | `CONSOLE_HTTPS=1` sets a Secure cookie; it only works over real HTTPS (Caddy) — over plain `http://` use `CONSOLE_HTTPS=0`. |
| Report screen won't render (others fine) | Fixed centrally (NaN→null in `to_dict`); make sure the running process has the latest `queries.py` (restart after pull). |
