"""
auth.py — Windows/network identity + basic RBAC for the Project Console.

Identity: the app is meant to run behind IIS with Windows Authentication, which passes
the authenticated domain login to the WSGI app as REMOTE_USER (e.g. 'MACR\\vnair').
We read that (or an X-Remote-User header from a reverse proxy). For local dev without
IIS, set CONSOLE_DEV_USER. In --demo there is no DB — a fixed demo user is used and
'?as=viewer|pm|admin' impersonates a role for testing the gates.

Roles (rank): viewer < pm < admin
  viewer — read all reports & dashboards
  pm     — + bring projects in / add-modify budgets  (write /api/pm/*)
  admin  — + manage users (/admin) and the crosswalk
Role is looked up per user in Reporting.tblConsoleUser; an unmapped domain user
defaults to 'viewer' (they're already inside Windows auth). Grant pm/admin explicitly.
"""
import os

from flask import request, jsonify, g, current_app

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
    """(username, role) for the current request. (None, None) if unauthenticated."""
    demo = current_app.config.get("DEMO")
    env = request.environ
    raw = (env.get("REMOTE_USER") or env.get("HTTP_REMOTE_USER")
           or env.get("HTTP_X_REMOTE_USER") or os.environ.get("CONSOLE_DEV_USER") or "")
    user = _norm(raw)
    if demo:
        if not user:
            user = "demo.user"
        as_ = (request.args.get("as") or "").lower()
        role = as_ if as_ in RANK else _DEMO_USERS.get(user, {}).get("role", "admin")
        return user, role
    if not user:
        return None, None
    return user, (_role_for(user) or "viewer")


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
