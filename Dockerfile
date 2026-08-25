# Project Console — one image, two homes.
#
# The SAME image runs on-prem today (LDAP form-login against the DC, SQL-auth to the
# ETO + Reporting databases) and, later, on Azure App Service with Entra ID SSO. Nothing
# tenant- or environment-specific is baked in: everything that differs is an env var
# (see .env.docker.example). The Windows-only auth path (pywin32 LogonUser) is skipped
# automatically on Linux — requirements.txt marks pywin32 `platform_system == "Windows"`,
# so on this Linux image auth.py falls back to the LDAP bind. That is why on-prem must run
# with CONSOLE_AUTH=ldap.
#
# Build:  docker build -t project-console:latest .
# Run:    docker run --env-file .env.docker -p 8000:8000 project-console:latest
#
# ---------------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm

# --- OS packages: the Microsoft ODBC Driver 17 (the version pinned in connections.py and
#     console_config.py) + the unixODBC runtime it needs. Installed from Microsoft's apt
#     repo. curl/gnupg are pulled in only to add the repo, then removed to keep the image
#     lean. ACCEPT_EULA is required for the driver package.
ENV ACCEPT_EULA=Y \
    DEBIAN_FRONTEND=noninteractive
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl gnupg ca-certificates apt-transport-https; \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
        | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg; \
    curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
        -o /etc/apt/sources.list.d/mssql-release.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends msodbcsql17 unixodbc; \
    apt-get purge -y --auto-remove curl gnupg apt-transport-https; \
    rm -rf /var/lib/apt/lists/*

# --- unixODBC connection pooling. The app opens a fresh DB connection per request; over the
#     Hybrid Connection each connect costs several relay round trips before the first query.
#     With pooling ON, the driver manager hands back a warm physical connection instead, so the
#     handshake is paid once and reused — a large latency win on the tunneled data path.
#     Pooling=Yes is global ([ODBC] section); CPTimeout is how long an idle pooled connection
#     stays reusable (seconds), set on the driver's section.
RUN printf '\n[ODBC]\nPooling=Yes\n' >> /etc/odbcinst.ini \
    && sed -i '/^\[ODBC Driver 17 for SQL Server\]/a CPTimeout=120' /etc/odbcinst.ini

# --- Python deps first (own layer, so app-code edits don't re-run the pip install).
#     pywin32 self-excludes on Linux via its platform marker; ldap3 stays in for the bind.
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Application code. .dockerignore keeps .git, .env, __pycache__, diagnostics, docs
#     and rendered outputs out of the build context.
COPY . .

# --- Run as an unprivileged user; the app writes nothing to the image at runtime.
#     Strip any CR from the entrypoint (a Windows CRLF checkout makes the shebang `bash\r`,
#     which fails to exec with exit 127) and chmod it, so the build never depends on the
#     checkout's line endings or the +x bit. Then hand the tree to the non-root user.
RUN sed -i 's/\r$//' /app/docker/docker-entrypoint.sh \
    && chmod +x /app/docker/docker-entrypoint.sh \
    && useradd --create-home --uid 10001 console \
    && chown -R console:console /app
USER console

# --- Sensible container defaults. CONSOLE_HTTPS is deliberately unset so serve_console.py
#     binds 0.0.0.0 (TLS is terminated by the platform / a reverse proxy in front, never
#     by waitress). Everything else — tenant, secret key, DB creds, LDAP — comes at runtime.
ENV CONSOLE_PORT=8000 \
    CONSOLE_THREADS=8 \
    PYTHONUNBUFFERED=1
EXPOSE 8000

# --- Liveness: hit the login page over the loopback. No curl in the image, so use Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os,urllib.request; \
urllib.request.urlopen('http://127.0.0.1:%s/login' % os.environ.get('CONSOLE_PORT','8000'), timeout=4)" \
    || exit 1

ENTRYPOINT ["/app/docker/docker-entrypoint.sh"]
CMD ["python", "serve_console.py"]
