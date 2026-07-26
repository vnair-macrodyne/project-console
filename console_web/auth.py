"""
auth.py — AD login-form identity + basic RBAC for the Project Console.

No IIS. Identity is established by an **LDAP bind against Active Directory**: the user
enters their existing domain username + password on /login, we bind to a DC over LDAPS
with those creds (no service account, no separate password store), and on success store
the username in the Flask session. Every later request reads the session.
  Config (env or tenant): CONSOLE_LDAP_SERVER (e.g. ldaps://dc01.macrodynepress.com),
  CONSOLE_AD_DOMAIN (UPN suffix, e.g. macrodynepress.com), CONSOLE_LDAP_SSL (default 1),
  CONSOLE_LDAP_TLS_VALIDATE (0 = accept the DC's self-signed cert; set 1 + a CA in prod).
In --demo there is no DC: any non-empty password logs in, the username maps to a role,
and '?as=viewer|pm|admin' still impersonates a role for testing the gates.

Roles (rank): viewer < pm < admin
  viewer — read all reports & dashboards
  pm     — + bring projects in / add-modify budgets  (write /api/pm/*)
  admin  — + manage users (/admin) and the crosswalk
Role is looked up per user in Reporting.tblConsoleUser; an authenticated domain user
not listed there defaults to 'viewer'. Grant pm/admin explicitly.
"""
import os

from flask import request, jsonify, g, current_app, session

RANK = {"viewer": 1, "pm": 2, "admin": 3}

# demo-only in-memory users (no DB); also lets the /admin screen be exercised with --demo
_DEMO_USERS = {
    "demo.user": {"role": "admin", "display": "Demo Admin"},
    "j.pm":      {"role": "pm",    "display": "Jamie (PM)"},
    "v.view":    {"role": "viewer", "display": "Val (Viewer)"},
}


def _norm(raw):
    """'MACR\\vnair' / 'vnair@macr' → 'vnair' (lowercased)."""
    return (raw or "").split("\\")[-1].split("@")[0].strip().lower()


def resolve_user():
    """(username, role) for the current request, from the session. (None, None) if not
    signed in. Demo: a signed-in session or the default demo user, with ?as= role override."""
    demo = current_app.config.get("DEMO")
    user = _norm(session.get("user") or "")
    if demo:
        if not user:
            user = os.environ.get("CONSOLE_DEV_USER", "demo.user")
        as_ = (request.args.get("as") or "").lower()
        role = as_ if as_ in RANK else _DEMO_USERS.get(user, {}).get("role", "admin")
        return user, role
    # dev convenience (no DC handy): CONSOLE_DEV_USER bypasses the login form
    if not user:
        user = _norm(os.environ.get("CONSOLE_DEV_USER") or "")
    if not user:
        return None, None
    return user, (_role_for(user) or "viewer")


def ldap_authenticate(username, password):
    """Verify (username, password) by binding to AD. Returns (ok, username, display_name).
    Demo: any non-empty password succeeds so the flow is exercisable without a DC."""
    username = _norm(username)
    if not username or not password:
        return False, None, None
    if current_app.config.get("DEMO"):
        return True, username, _DEMO_USERS.get(username, {}).get("display", username)

    from console.config import TENANT
    server_host = os.environ.get("CONSOLE_LDAP_SERVER") or getattr(TENANT, "ldap_server", None)
    domain = os.environ.get("CONSOLE_AD_DOMAIN") or getattr(TENANT, "ad_domain", None)
    if not server_host or not domain:
        raise RuntimeError("LDAP not configured — set CONSOLE_LDAP_SERVER and CONSOLE_AD_DOMAIN")
    use_ssl = os.environ.get("CONSOLE_LDAP_SSL", "1") != "0"
    validate = os.environ.get("CONSOLE_LDAP_TLS_VALIDATE", "0") == "1"

    import ssl as _ssl
    from ldap3 import Server, Connection, Tls, ALL
    tls = Tls(validate=_ssl.CERT_REQUIRED if validate else _ssl.CERT_NONE) if use_ssl else None
    server = Server(server_host, use_ssl=use_ssl, tls=tls, get_info=ALL)
    upn = f"{username}@{domain}"          # AD accepts UPN bind
    conn = Connection(server, user=upn, password=password, authentication="SIMPLE")
    if not conn.bind():
        return False, None, None
    display = username
    try:  # best-effort: read the user's display name (as the just-bound user)
        base = ",".join(f"DC={p}" for p in domain.split("."))
        conn.search(base, f"(sAMAccountName={username})", attributes=["displayName"])
        if conn.entries and conn.entries[0].displayName:
            display = str(conn.entries[0].displayName)
    except Exception:
        pass
    conn.unbind()
    return True, username, display


def _role_for(user):
    try:
        from console.infra.connections import console_connection
        conn = console_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT Role FROM Reporting.tblConsoleUser WHERE LOWER(Username) = ?", user)
            row = cur.fetchone()
        finally:
            conn.close()
        return row[0].strip().lower() if row and row[0] else None
    except Exception:
        return None


def gate(min_role):
    """None if g.role satisfies min_role, else a Flask (response, status) to return."""
    if not getattr(g, "user", None):
        return jsonify({"error": "not authenticated (Windows sign-in not detected)"}), 401
    if RANK.get(getattr(g, "role", None), 0) < RANK[min_role]:
        return jsonify({"error": f"requires {min_role} access"}), 403
    return None


# ── admin: manage the user→role map ───────────────────────────────────────────
def list_users():
    if current_app.config.get("DEMO"):
        return [{"username": u, "role": d["role"], "display": d.get("display", "")}
                for u, d in sorted(_DEMO_USERS.items())]
    from console.infra.connections import console_connection
    conn = console_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT Username, Role, DisplayName FROM Reporting.tblConsoleUser ORDER BY Username")
        return [{"username": r[0], "role": (r[1] or "viewer").lower(), "display": r[2] or ""}
                for r in cur.fetchall()]
    finally:
        conn.close()


def set_user(username, role, display, by):
    username = _norm(username)
    role = (role or "").lower()
    if not username or role not in RANK:
        raise ValueError("username and role (viewer|pm|admin) required")
    if current_app.config.get("DEMO"):
        _DEMO_USERS[username] = {"role": role, "display": display or ""}
        return
    from console.infra.connections import console_connection
    from console.infra.db import ex
    conn = console_connection()
    try:
        cur = conn.cursor()
        ex(cur,
           "MERGE Reporting.tblConsoleUser AS t USING (SELECT ? AS Username) s "
           "ON LOWER(t.Username) = LOWER(s.Username) "
           "WHEN MATCHED THEN UPDATE SET Role=?, DisplayName=?, UpdatedAt=GETDATE(), UpdatedBy=? "
           "WHEN NOT MATCHED THEN INSERT(Username,Role,DisplayName,UpdatedBy) VALUES(?,?,?,?);",
           username, role, display, by, username, role, display, by)
        conn.commit()
    finally:
        conn.close()


def remove_user(username, by):
    username = _norm(username)
    if current_app.config.get("DEMO"):
        _DEMO_USERS.pop(username, None)
        return
    from console.infra.connections import console_connection
    conn = console_connection()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM Reporting.tblConsoleUser WHERE LOWER(Username) = ?", username)
        conn.commit()
    finally:
        conn.close()
