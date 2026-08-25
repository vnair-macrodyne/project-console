"""
auth.py — AD login-form identity + basic RBAC for the Project Console.

No IIS. Identity is established against **Active Directory** with the user's own
domain username + password entered on /login (no service account, no separate
password store); on success the username is stored in the Flask session and every
later request reads the session. Three backends, none of which need a DC certificate
except LDAPS/SIMPLE:
  • windows  — Windows LogonUser (pywin32). The OS validates the password against AD.
               No LDAP server or cert. Default on Windows. Needs CONSOLE_AD_DOMAIN.
  • ldap+ntlm — ldap3 NTLM bind as NETBIOS\\user over port 389. Challenge/response,
               so the password never crosses the wire in cleartext, and NO cert is
               needed. The go-to when LDAPS isn't set up. Default LDAP style.
  • ldap+simple — ldap3 SIMPLE bind as user@domain over LDAPS (636). Needs a valid
               LDAPS cert on the DC; use only when that exists.
  Backend: CONSOLE_AUTH = windows | ldap (auto: windows if pywin32 present, else ldap).
  LDAP style: CONSOLE_LDAP_METHOD = ntlm | simple (auto: simple if SSL, else ntlm).
  Config (env or tenant): CONSOLE_LDAP_SERVER (host or ldap[s]://host),
  CONSOLE_AD_DOMAIN (UPN suffix, e.g. macrodynepress.com), CONSOLE_AD_NETBIOS
  (short domain for NTLM; defaults to the first label of the UPN suffix),
  CONSOLE_LDAP_SSL (default 0 → 389/NTLM, no cert), CONSOLE_LDAP_TLS_VALIDATE.
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


def auth_mode():
    """Which backend is active: 'windows' | 'ldap' | 'entra'.
    From CONSOLE_AUTH if set to a known value, else auto (windows if pywin32 present, else ldap)."""
    m = (os.environ.get("CONSOLE_AUTH") or "").lower()
    if m in ("windows", "ldap", "entra"):
        return m
    return "windows" if _win_available() else "ldap"


def is_entra():
    """True when Entra SSO is the active backend (redirect flow, not the password form).
    Never true in demo, which keeps the DB-free password form working for eval/screenshots."""
    if current_app.config.get("DEMO"):
        return False
    return auth_mode() == "entra"


def authenticate(username, password):
    """Verify a domain user's (username, password). Returns (ok, username, display_name).
    Method (env CONSOLE_AUTH): 'windows' (pywin32 LogonUser — no LDAP server/cert needed) or
    'ldap' (ldap3 bind). Default: Windows when pywin32 is available, else LDAP.
    Demo: any non-empty password succeeds so the flow works without a DC.
    Entra mode has no password form — sign-in goes through entra_begin()/entra_complete()."""
    username = _norm(username)
    if not username or not password:
        return False, None, None
    if current_app.config.get("DEMO"):
        return True, username, _DEMO_USERS.get(username, {}).get("display", username)
    method = auth_mode()
    if method == "entra":
        # form login is disabled under Entra; the redirect flow is the only path
        return False, None, None
    if method == "windows":
        return _win_authenticate(username, password)
    return _ldap_authenticate(username, password)


# back-compat alias
ldap_authenticate = authenticate


def _win_available():
    try:
        import win32security  # noqa: F401
        return True
    except Exception:
        return False


def _win_authenticate(username, password):
    """Validate the domain password via the Windows LogonUser API (pywin32). No LDAP server
    or LDAPS certificate needed — the OS authenticates against AD. Needs CONSOLE_AD_DOMAIN
    (UPN suffix, e.g. macrodynepress.com) so we log on as user@domain."""
    from console.config import TENANT
    import win32security
    import win32con
    domain = os.environ.get("CONSOLE_AD_DOMAIN") or getattr(TENANT, "ad_domain", None)
    if domain and "@" not in username and "\\" not in username:
        user_arg, dom_arg = f"{username}@{domain}", None          # UPN logon
    else:
        user_arg, dom_arg = username, (os.environ.get("CONSOLE_AD_NETBIOS") or None)
    try:
        handle = win32security.LogonUser(
            user_arg, dom_arg, password,
            win32con.LOGON32_LOGON_NETWORK, win32con.LOGON32_PROVIDER_DEFAULT)
        handle.Close()
        return True, username, username
    except Exception:
        return False, None, None


def _ldap_authenticate(username, password):
    """Verify (username, password) by binding to Active Directory with ldap3.

    Two bind styles, chosen by CONSOLE_LDAP_METHOD (or auto):
      • ntlm   — NTLM bind as NETBIOS\\user over port 389 (no SSL). NTLM is
                 challenge/response so the password never crosses the wire in
                 cleartext, and it needs NO certificate on the DC. This is the
                 default and the one to use when LDAPS isn't set up.
      • simple — SIMPLE bind as user@domain over LDAPS (636). Requires the DC to
                 present a valid LDAPS certificate; use only when that's in place.
    Auto: 'simple' if the server is ldaps:// or CONSOLE_LDAP_SSL=1, else 'ntlm'.
    Env: CONSOLE_LDAP_SERVER (host or ldap[s]://host), CONSOLE_AD_DOMAIN (UPN
    suffix), CONSOLE_AD_NETBIOS (short domain for NTLM; falls back to the first
    label of the UPN suffix, upper-cased), CONSOLE_LDAP_TLS_VALIDATE (SSL only)."""
    from console.config import TENANT
    server_host = os.environ.get("CONSOLE_LDAP_SERVER") or getattr(TENANT, "ldap_server", None)
    domain = os.environ.get("CONSOLE_AD_DOMAIN") or getattr(TENANT, "ad_domain", None)
    if not server_host or not domain:
        raise RuntimeError("LDAP not configured — set CONSOLE_LDAP_SERVER and CONSOLE_AD_DOMAIN")

    host_l = server_host.lower()
    # explicit scheme in the host wins; else honour CONSOLE_LDAP_SSL (default off → no cert needed)
    if host_l.startswith("ldaps://"):
        use_ssl = True
    elif host_l.startswith("ldap://"):
        use_ssl = os.environ.get("CONSOLE_LDAP_SSL") == "1"
    else:
        use_ssl = os.environ.get("CONSOLE_LDAP_SSL", "0") == "1"
    method = (os.environ.get("CONSOLE_LDAP_METHOD") or "").lower()
    if method not in ("ntlm", "simple"):
        method = "simple" if use_ssl else "ntlm"

    import ssl as _ssl
    from ldap3 import Server, Connection, Tls, ALL, NTLM, SIMPLE
    validate = os.environ.get("CONSOLE_LDAP_TLS_VALIDATE", "0") == "1"
    tls = Tls(validate=_ssl.CERT_REQUIRED if validate else _ssl.CERT_NONE) if use_ssl else None
    server = Server(server_host, use_ssl=use_ssl, tls=tls, get_info=ALL)

    if method == "ntlm":
        netbios = (os.environ.get("CONSOLE_AD_NETBIOS") or domain.split(".")[0]).upper()
        conn = Connection(server, user=f"{netbios}\\{username}", password=password,
                          authentication=NTLM)
    else:
        conn = Connection(server, user=f"{username}@{domain}", password=password,
                          authentication=SIMPLE)
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


# ── Entra ID (Azure AD) SSO — OpenID Connect authorization-code flow ───────────
# The Azure end-state: users sign in with their Entra ID, so the app needs NO on-prem
# reach for identity (only the SQL data path remains). This is a redirect flow, not a
# password form: /login → entra_begin() bounces to Entra; Entra returns to the redirect
# URI → entra_complete() validates and yields (username, display). Role still comes from
# Reporting.tblConsoleUser keyed on the normalized username, exactly as for windows/ldap,
# so the viewer<pm<admin gates and the /admin screen are unchanged.
#
# Config (env; secret via Key Vault reference on Azure):
#   CONSOLE_ENTRA_TENANT_ID       the Entra tenant (directory) id
#   CONSOLE_ENTRA_CLIENT_ID       the app registration's application (client) id
#   CONSOLE_ENTRA_CLIENT_SECRET   a client secret on that app registration
#   CONSOLE_ENTRA_REDIRECT_URI    optional explicit callback URL; else built from the request
#                                 (ProxyFix gives the real https host) + CONSOLE_ENTRA_REDIRECT_PATH
#   CONSOLE_ENTRA_REDIRECT_PATH   default /auth/callback
#   CONSOLE_ENTRA_AUTHORITY       optional override (default https://login.microsoftonline.com/<tenant>)
#   CONSOLE_ENTRA_SCOPES          optional extra resource scopes (space-separated); default sign-in only
# msal is imported lazily so windows/ldap deployments without it are unaffected.
_ENTRA_FLOW_KEY = "_entra_flow"
_ENTRA_NEXT_KEY = "_entra_next"


def _entra_cfg():
    tid = os.environ.get("CONSOLE_ENTRA_TENANT_ID")
    cid = os.environ.get("CONSOLE_ENTRA_CLIENT_ID")
    secret = os.environ.get("CONSOLE_ENTRA_CLIENT_SECRET")
    if not (tid and cid and secret):
        raise RuntimeError("Entra not configured — set CONSOLE_ENTRA_TENANT_ID, "
                           "CONSOLE_ENTRA_CLIENT_ID and CONSOLE_ENTRA_CLIENT_SECRET")
    authority = os.environ.get("CONSOLE_ENTRA_AUTHORITY") or \
        f"https://login.microsoftonline.com/{tid}"
    return cid, secret, authority


def _entra_app():
    import msal  # lazy: only needed under Entra
    cid, secret, authority = _entra_cfg()
    return msal.ConfidentialClientApplication(cid, authority=authority, client_credential=secret)


def _entra_scopes():
    return [s for s in (os.environ.get("CONSOLE_ENTRA_SCOPES") or "").split() if s]


def entra_redirect_uri():
    """Absolute callback URL. Explicit override wins; else build from the current request so it
    works for whichever host (staging vs prod) is serving. Must match a redirect URI registered
    on the Entra app registration."""
    uri = os.environ.get("CONSOLE_ENTRA_REDIRECT_URI")
    if uri:
        return uri
    path = os.environ.get("CONSOLE_ENTRA_REDIRECT_PATH", "/auth/callback")
    return request.url_root.rstrip("/") + path


def entra_begin(next_url):
    """Start the auth-code flow: stash the MSAL flow (state + nonce + PKCE) and the post-login
    target in the session, and return the Entra authorization URL to redirect the browser to."""
    flow = _entra_app().initiate_auth_code_flow(_entra_scopes(), redirect_uri=entra_redirect_uri())
    session[_ENTRA_FLOW_KEY] = flow
    session[_ENTRA_NEXT_KEY] = next_url if (next_url or "/").startswith("/") else "/"
    return flow["auth_uri"]


def entra_complete(auth_response):
    """Finish the flow from the redirect query params (auth_response = request.args). MSAL
    validates state + nonce against the stashed flow. Returns (ok, username, display, next_url)."""
    flow = session.pop(_ENTRA_FLOW_KEY, None)
    nxt = session.pop(_ENTRA_NEXT_KEY, "/") or "/"
    if not nxt.startswith("/"):
        nxt = "/"
    if not flow:
        return False, None, None, nxt
    result = _entra_app().acquire_token_by_auth_code_flow(flow, dict(auth_response))
    if not isinstance(result, dict) or "error" in result or "id_token_claims" not in result:
        return False, None, None, nxt
    claims = result["id_token_claims"]
    upn = (claims.get("preferred_username") or claims.get("upn")
           or claims.get("email") or "")
    display = claims.get("name") or upn
    user = _norm(upn)
    if not user:
        return False, None, None, nxt
    return True, user, display, nxt


def entra_logout_url(post_logout_redirect=None):
    """Entra single-logout URL (optional). Clears the Entra session too, not just the app cookie."""
    _, _, authority = _entra_cfg()
    url = authority.rstrip("/") + "/oauth2/v2.0/logout"
    if post_logout_redirect:
        from urllib.parse import urlencode
        url += "?" + urlencode({"post_logout_redirect_uri": post_logout_redirect})
    return url


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
