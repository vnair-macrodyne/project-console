"""
Project Console — web query interface (Flask).

Routes
  GET  /                     the single-page app
  GET  /api/branding         product/company/colour for the header
  GET  /api/queries          the query catalogue (drives the dropdown)
  GET  /api/projects         selectable projects (id + label + ship date)
  POST /api/query            run a query -> QueryResult JSON
  POST /api/export/<fmt>     xlsx | pdf of a QueryResult (re-run server-side)

A fresh QueryService is built per request so DB connections never outlive the
request. `--demo` swaps in the DB-free backend so the whole thing runs with no
database (used for the screenshot verification and for sales/eval demos).

Run:
  python -m console_web.app            # live (needs .env + DBs)
  python -m console_web.app --demo     # canned data, no DB
"""
import argparse

from flask import (Flask, jsonify, request, send_file, render_template, g,
                   redirect, url_for, session)
import io
import os

from console_web.queries import make_service, catalogue, branding
from console_web import exporters, auth
from console_web.pm import make_pm_service

app = Flask(__name__)
app.config["DEMO"] = False
# Session signing key — set CONSOLE_SECRET_KEY in prod so sessions survive restarts.
app.secret_key = os.environ.get("CONSOLE_SECRET_KEY") or os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


def _service():
    return make_service(demo=app.config["DEMO"])


def _run_from_payload(payload):
    payload = payload or {}
    query_id = payload.get("query_id")
    project_ids = payload.get("project_ids") or []
    date_from = payload.get("date_from") or None
    date_to = payload.get("date_to") or None
    view = payload.get("view") or "period"
    svc = _service()
    try:
        return svc.run(query_id, project_ids, date_from=date_from, date_to=date_to, view=view)
    finally:
        close = getattr(svc, "close", None)
        if close:
            close()


# ── Auth: AD login form → session identity; unauth pages go to /login ─────────
_EXEMPT = {"/login", "/logout", "/api/login", "/api/me"}


@app.before_request
def _auth_ctx():
    g.user, g.role = auth.resolve_user()
    p = request.path
    if p in _EXEMPT or p.startswith("/static"):
        return
    if not g.user:
        if p.startswith("/api/"):
            return jsonify({"error": "not authenticated"}), 401
        return redirect(url_for("login_page", next=p))


@app.route("/login", methods=["GET", "POST"])
def login_page():
    from console.config import TENANT
    nxt = request.values.get("next") or "/"
    if not nxt.startswith("/"):
        nxt = "/"
    err = None
    if request.method == "POST":
        u = request.form.get("username", "")
        pw = request.form.get("password", "")
        try:
            ok, user, display = auth.ldap_authenticate(u, pw)
        except Exception as e:
            app.logger.exception("ldap auth error")
            ok, user, display, err = False, None, None, "Sign-in is not configured. Contact IT."
        if ok:
            session.clear()
            session["user"] = user
            session["display"] = display or user
            return redirect(nxt)
        err = err or "Invalid username or password."
    return render_template("login.html", error=err, product=TENANT.product_name,
                           company=TENANT.company_name,
                           environment=getattr(TENANT, "environment", "prod"), next=nxt)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/api/me")
def api_me():
    return jsonify({"user": g.get("user"), "role": g.get("role"),
                    "display": session.get("display"),
                    "demo": app.config["DEMO"], "environment": _environment()})


def _environment():
    try:
        from console.config import TENANT
        return getattr(TENANT, "environment", "prod")
    except Exception:
        return "prod"


@app.route("/")
def index():
    return render_template("index.html")


# ── PM controls: bring a project in + author/edit its budget ──────────────────
@app.route("/pm")
def pm_page():
    return render_template("pm.html")


def _pm_service():
    return make_pm_service(demo=app.config["DEMO"])


def _pm_call(fn):
    svc = _pm_service()
    try:
        return fn(svc)
    finally:
        close = getattr(svc, "close", None)
        if close:
            close()


@app.route("/api/pm/scaffold")
def api_pm_scaffold():
    try:
        data = _pm_call(lambda s: s.scaffold())
        data["branding"] = branding()
        data["demo"] = app.config["DEMO"]
        return jsonify(data)
    except Exception as e:
        app.logger.exception("pm scaffold failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/pm/projects")
def api_pm_projects():
    try:
        return jsonify(_pm_call(lambda s: s.list_projects()))
    except Exception as e:
        app.logger.exception("pm projects failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/pm/budget/<int:pid>")
def api_pm_get_budget(pid):
    try:
        return jsonify(_pm_call(lambda s: s.get_budget(pid)))
    except Exception as e:
        app.logger.exception("pm get_budget failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/pm/budget", methods=["POST"])
def api_pm_save_budget():
    denied = auth.gate("pm")           # only PM / Admin may write budgets
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    if not payload.get("project_id"):
        return jsonify({"error": "project_id is required"}), 400
    payload.setdefault("entered_by", g.get("user"))   # stamp the signed-in user
    try:
        return jsonify(_pm_call(lambda s: s.save_budget(payload)))
    except Exception as e:
        app.logger.exception("pm save_budget failed")
        return jsonify({"error": str(e)}), 500


# ── Admin: manage the user → role map (Admin only) ────────────────────────────
@app.route("/admin")
def admin_page():
    return render_template("admin.html")


@app.route("/api/admin/users", methods=["GET"])
def api_admin_users():
    denied = auth.gate("admin")
    if denied:
        return denied
    try:
        return jsonify({"users": auth.list_users()})
    except Exception as e:
        app.logger.exception("admin users list failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/users", methods=["POST"])
def api_admin_set_user():
    denied = auth.gate("admin")
    if denied:
        return denied
    b = request.get_json(silent=True) or {}
    if not b.get("username") or (b.get("role") or "").lower() not in ("viewer", "pm", "admin"):
        return jsonify({"error": "username and role (viewer|pm|admin) required"}), 400
    try:
        auth.set_user(b["username"], b["role"], b.get("display"), g.get("user"))
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("admin set_user failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/admin/users/<username>", methods=["DELETE"])
def api_admin_del_user(username):
    denied = auth.gate("admin")
    if denied:
        return denied
    try:
        auth.remove_user(username, g.get("user"))
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("admin del_user failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/branding")
def api_branding():
    b = branding()
    b["demo"] = app.config["DEMO"]
    return jsonify(b)


@app.route("/api/queries")
def api_queries():
    return jsonify(catalogue())


@app.route("/api/projects")
def api_projects():
    svc = _service()
    try:
        return jsonify(svc.list_projects())
    except Exception as e:
        app.logger.exception("project list failed")
        return jsonify({"error": str(e)}), 500
    finally:
        close = getattr(svc, "close", None)
        if close:
            close()


@app.route("/api/query", methods=["POST"])
def api_query():
    try:
        result = _run_from_payload(request.get_json(silent=True))
        return jsonify(result.to_dict())
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.exception("query failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/<fmt>", methods=["POST"])
def api_export(fmt):
    fmt = fmt.lower()
    if fmt not in ("xlsx", "pdf"):
        return jsonify({"error": "format must be xlsx or pdf"}), 400
    try:
        result = _run_from_payload(request.get_json(silent=True))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.exception("export query failed")
        return jsonify({"error": str(e)}), 500

    if fmt == "xlsx":
        data = exporters.to_xlsx(result)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        data = exporters.to_pdf(result)
        mime = "application/pdf"
    return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True,
                     download_name=exporters.filename(result, fmt))


def main():
    ap = argparse.ArgumentParser(description="Project Console web query interface")
    ap.add_argument("--demo", action="store_true",
                    help="run with canned data, no database")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    app.config["DEMO"] = args.demo
    if args.demo:
        print("Project Console web — DEMO mode (no database)")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
