"""
serve_console.py — start Project Console under waitress.

Launched by run_console.ps1 (or run directly: `python serve_console.py`). Keeping the launch in a
.py file avoids PowerShell mis-parsing an inline `python -c "..."` one-liner. Reads the environment
the caller set (CONSOLE_HTTPS decides the bind host; CONSOLE_PORT/THREADS optional).
"""
import os
from waitress import serve
from console_web.app import app   # importing as a module starts the warm-cache daemon

host = "127.0.0.1" if os.environ.get("CONSOLE_HTTPS") == "1" else "0.0.0.0"
port = int(os.environ.get("CONSOLE_PORT", "8000"))
threads = int(os.environ.get("CONSOLE_THREADS", "8"))

print(f"Project Console starting on {host}:{port}  "
      f"(CONSOLE_HTTPS={os.environ.get('CONSOLE_HTTPS')}, threads={threads})", flush=True)
serve(app, host=host, port=port, threads=threads)
