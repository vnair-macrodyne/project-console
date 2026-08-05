# Project Console — Local (Laptop) Deployment & Run

**Scope:** running Project Console on a **developer / domain‑joined laptop** for testing and
iteration. For the production server see `DEPLOY_SERVER.md`.

**What it connects to:** the **staging** reporting store (`Macrodyne_Reporting_Staging`) plus the
**live, read‑only** ETO database (`Macrodyne_Production`) on `MACRO-ETO-SVR\SQLEXPRESS`. Nothing you
do locally writes to prod ETO.

---

## 1. One‑time setup

1. **Get the code** — clone/pull the repo. On the laptop it lives at:
   `C:\Users\vijay\OneDrive\Macrodyne\Reporting\project-console`

2. **Python 3.11+** installed and on PATH (`python --version`).

3. **Install dependencies** (once):
   ```powershell
   pip install waitress pywin32 pyodbc cryptography
   pip install -r requirements.txt      # if the repo has one
   ```
   Also install **ODBC Driver 17 for SQL Server** (Microsoft download) if it isn't already.

4. **Create `console_secrets.ps1`** in the repo root (this file is **not** committed — add it to
   `.gitignore`). Use **single quotes** so a `$` in a password isn't eaten by PowerShell:
   ```powershell
   # console_secrets.ps1  — DO NOT COMMIT
   $env:CONSOLE_ENV        = 'staging'                     # -> Macrodyne_Reporting_Staging store
   $env:CONSOLE_STORE_USER = 'MacrodyneConsoleSvc'; $env:CONSOLE_STORE_PWD = 'the$store$password'
   $env:ETO_USER           = 'TotalETOReportWriter';  $env:ETO_PWD         = 'the$eto$password'
   $env:CONSOLE_SECRET_KEY = 'a-fixed-random-string'      # generate once, keep constant
   ```
   Generate the secret key once: `python -c "import secrets; print(secrets.token_hex(32))"`.

---

## 2. Startup

From the repo folder, in PowerShell:

```powershell
cd "C:\Users\vijay\OneDrive\Macrodyne\Reporting\project-console"
. .\console_secrets.ps1                          # load creds + CONSOLE_ENV + secret key
$env:CONSOLE_TENANT    = "tenant_macrodyne.json"
$env:CONSOLE_AUTH      = "windows"                # login validated via the OS (needs pywin32)
$env:CONSOLE_AD_DOMAIN = "macrodynepress.com"
$env:CONSOLE_HTTPS     = "0"                      # 0 = plain HTTP, binds 0.0.0.0 (fine for a laptop)
python serve_console.py
```

The startup line should read **`Project Console starting on 0.0.0.0:8000`** and then log
`built N ETO budgets …` once (the warm cache priming). Leave the window open — it runs in the
foreground.

**Access it:**
- On the laptop itself: `http://127.0.0.1:8000/`
- Sign in with your **AD username** (e.g. `vnair`) and **AD password** — `CONSOLE_AUTH=windows`
  logs you on as `user@macrodynepress.com` through Windows, no LDAP server needed.

> Quicker inner loop (optional): `python -m flask --app console_web.app run --port 5000` runs the
> Flask dev server. Do **not** pass `--debug` — its auto‑reloader starts the background cache
> thread twice.

---

## 3. Shutdown

- Press **Ctrl+C** in the window running it. That's it — nothing persists, no service to stop.

## 4. Restart after a code change

Pulling new code does **not** affect a process that's already running — Python loaded the old code
at startup. Always **Ctrl+C and start again** after a `git pull` (or after editing any `.py`).

---

## 5. Everyday commands (cheat sheet)

```powershell
# start
cd "C:\Users\vijay\OneDrive\Macrodyne\Reporting\project-console"; . .\console_secrets.ps1
$env:CONSOLE_TENANT="tenant_macrodyne.json"; $env:CONSOLE_AUTH="windows"
$env:CONSOLE_AD_DOMAIN="macrodynepress.com"; $env:CONSOLE_HTTPS="0"
python serve_console.py

# stop:            Ctrl+C
# update + restart: git pull   (then Ctrl+C and start again)
```

---

## 6. Troubleshooting (things we actually hit)

| Symptom | Cause / Fix |
|---|---|
| `waitress-serve : not recognized` | Scripts dir not on PATH. Use `python serve_console.py` (it imports waitress) — never the `waitress-serve` exe. |
| PowerShell parse error on a `python -c "…"` line | PS mis‑parses inline Python. Use `serve_console.py`, don't inline. |
| `running scripts is disabled` | `powershell -ExecutionPolicy Bypass -File .\run_console.ps1`, or just run `python serve_console.py` directly. |
| `LDAP not configured` at login | `pip install pywin32` and set `CONSOLE_AUTH=windows` + `CONSOLE_AD_DOMAIN`. |
| `Login failed for user 'MacrodyneConsoleSvc'` / `Cannot open database` (4060) | You're pointed at **prod** `Macrodyne_Reporting`, which that login can't open. Set `CONSOLE_ENV=staging` (→ `Macrodyne_Reporting_Staging`). |
| Password "looks right" but rejected | A `$` in the password was expanded — use **single quotes** in `console_secrets.ps1`. |
| `WARNING … Reporting.tlkpHourTypeDiscipline` | Benign; run `console_seed_hourtype.py` once against the staging store to silence it. |
| Signed in but bounced back to login | You're on `http://` with `CONSOLE_HTTPS=1` (Secure cookie). Use `CONSOLE_HTTPS=0` for plain‑HTTP local runs. |
