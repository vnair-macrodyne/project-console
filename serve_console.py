"""
serve_console.py — start Project Console under waitress.

Launched by run_console.ps1 (or run directly: `python serve_console.py`). Keeping the launch in a
.py file avoids PowerShell mis-parsing an inline `python -c "..."` one-liner. Reads the environment
the caller set (CONSOLE_HTTPS decides secure-cookie hardening; CONSOLE_BIND_HOST/PORT/THREADS optional).
"""
import os
from waitress import serve
from console_web.app import app   # importing as a module starts the warm-cache daemon

# Bind host. Precedence:
#   1. CONSOLE_BIND_HOST if set — explicit override (containers on Azure App Service MUST bind
#      0.0.0.0 so the platform can reach the container over the bridge network, even though
#      CONSOLE_HTTPS=1 is also set there to turn on secure cookies — see the note below).
#   2. else 127.0.0.1 when CONSOLE_HTTPS=1 — the on-prem case: waitress sits behind Caddy on the
#      same host, so it should only listen on loopback and let Caddy hold the cert on :443.
#   3. else 0.0.0.0 — plain HTTP on the LAN, no reverse proxy.
# CONSOLE_HTTPS still independently drives the app's secure-cookie / HSTS hardening (in app.py);
# decoupling the bind host lets a TLS-terminating platform (App Service) get both: 0.0.0.0 + secure.
_bind = os.environ.get("CONSOLE_BIND_HOST")
if _bind:
    host = _bind
elif os.environ.get("CONSOLE_HTTPS") == "1":
    host = "127.0.0.1"
else:
    host = "0.0.0.0"
port = int(os.environ.get("CONSOLE_PORT", "8000"))
threads = int(os.environ.get("CONSOLE_THREADS", "8"))

print(f"Project Console starting on {host}:{port}  "
      f"(CONSOLE_HTTPS={os.environ.get('CONSOLE_HTTPS')}, "
      f"CONSOLE_BIND_HOST={os.environ.get('CONSOLE_BIND_HOST')}, threads={threads})", flush=True)
serve(app, host=host, port=port, threads=threads)
