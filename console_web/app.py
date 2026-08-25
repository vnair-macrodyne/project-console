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

from werkzeug.middleware.proxy_fix import ProxyFix

from console_web.queries import make_service, catalogue, branding, data_watermark
from console_web import exporters, auth, cache as cache_mod
from console_web.pm import make_pm_service
from console_web.plan import make_plan_service

app = Flask(__name__)
app.config["DEMO"] = False
# Session signing key — set CONSOLE_SECRET_KEY in prod so sessions survive restarts.
app.secret_key = os.environ.get("CONSOLE_SECRET_KEY") or os.urandom(32)

# HTTPS hardening. Set CONSOLE_HTTPS=1 once the app is served behind the TLS reverse
# proxy (Caddy/nginx on the same host). Then the session cookie is only sent over TLS,
# and HSTS is emitted. Leave unset while still on plain HTTP so nothing locks you out
# mid-migration.
_HTTPS = os.environ.get("CONSOLE_HTTPS", "").strip().lower() in ("1", "true", "yes", "on")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=_HTTPS)
# Behind the local TLS terminator, trust its X-Forwarded-* so url_for/redirects, the
# secure-cookie decision and request.is_secure see the real https scheme + host.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)


@app.after_request
def _security_headers(resp):
    # nosniff also stops browsers second-guessing the export MIME type on download.
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    if _HTTPS:
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resp


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


# ── Dashboard warm cache ──────────────────────────────────────────────────────
# The Executive board / scorecard re-ran the heavy live ETO aggregations on every
# open. cache_mod keeps their computed payloads warm in memory and refreshes them
# in the background only when the underlying data actually moves, so requests serve
# instantly. See console_web/cache.py for the full design.
def _warm_dashboard(watermark):
    """Recompute the hot dashboard payloads under `watermark`. Runs in the cache's
    background thread with its own short-lived service (fresh crosswalk/overlay)."""
    keys = cache_mod.cache.hot_keys()
    svc = make_service(demo=False)
    try:
        if not keys:
            # nothing observed yet — prime the default board (all active projects),
            # which is exactly what the UI requests on load (it pre-selects all).
            ids = [p["id"] for p in svc.list_projects()]
            keys = [cache_mod.cache.key(qid, ids) for qid in cache_mod.HOT_QUERIES]
            for k in keys:
                cache_mod.cache.remember(k)
        for query_id, pids in keys:
            res = svc.run(query_id, list(pids))
            cache_mod.cache.put(cache_mod.cache.key(query_id, pids), res.to_dict(), watermark)
    finally:
        close = getattr(svc, "close", None)
        if close:
            close()


def _ensure_cache():
    if not app.config["DEMO"]:
        cache_mod.cache.start(_warm_dashboard, data_watermark)


def _serve_dashboard(payload):
    """Serve a Dashboard query from the warm cache; compute+cache live on a miss."""
    _ensure_cache()
    query_id = payload.get("query_id")
    ids = payload.get("project_ids") or []
    if not ids:
        # nothing selected -> run live (empty board); don't cache an empty scope
        return jsonify(_run_from_payload(payload).to_dict())
    key = cache_mod.cache.key(query_id, ids)
    wm = cache_mod.cache.current_watermark()
    entry = cache_mod.cache.get(key)
    if entry and wm is not None and entry["watermark"] == wm:
        out = dict(entry["result"])
        out["as_of"] = entry["as_of"]
        out["cached"] = True
        return jsonify(out)
    # miss or stale: compute once, cache it, register the scope as hot
    result = _run_from_payload(payload).to_dict()
    as_of = cache_mod.cache.put(key, result, wm)
    cache_mod.cache.remember(key)
    out = dict(result)
    out["as_of"] = as_of
    out["cached"] = False
    return jsonify(out)


# ── Auth: AD login form → session identity; unauth pages go to /login ─────────
_EXEMPT = {"/login", "/logout", "/api/login", "/api/me", "/auth/callback"}


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
    # Entra SSO: no password form — bounce straight to Entra's sign-in.
    if auth.is_entra():
        try:
            return redirect(auth.entra_begin(nxt))
        except Exception:
            app.logger.exception("entra begin")
            return render_template("login.html", error="Single sign-on is not configured. Contact IT.",
                                   product=TENANT.product_name, company=TENANT.company_name,
                                   logo=getattr(TENANT, "logo_path", ""),
                                   environment=getattr(TENANT, "environment", "prod"), next=nxt)
    if request.method == "POST":
        u = request.form.get("username", "")
        pw = request.form.get("password", "")
        try:
            ok, user, display = auth.authenticate(u, pw)
        except Exception as e:
            app.logger.exception("auth error")
            ok, user, display, err = False, None, None, "Sign-in is not configured. Contact IT."
        if ok:
            session.clear()
            session["user"] = user
            session["display"] = display or user
            return redirect(nxt)
        err = err or "Invalid username or password."
    return render_template("login.html", error=err, product=TENANT.product_name,
                           company=TENANT.company_name,
                           logo=getattr(TENANT, "logo_path", ""),
                           environment=getattr(TENANT, "environment", "prod"), next=nxt)


@app.route("/auth/callback")
def auth_callback():
    """Entra redirect URI — completes the auth-code flow and establishes the session."""
    try:
        ok, user, display, nxt = auth.entra_complete(request.args)
    except Exception:
        app.logger.exception("entra callback")
        ok, nxt = False, "/"
    if not ok:
        return redirect(url_for("login_page"))
    session.clear()
    session["user"] = user
    session["display"] = display or user
    return redirect(nxt if nxt.startswith("/") else "/")


@app.route("/logout")
def logout():
    was_entra = auth.is_entra()
    session.clear()
    # Optionally end the Entra session too (single logout), not just the app cookie.
    if was_entra and os.environ.get("CONSOLE_ENTRA_SLO") == "1":
        try:
            return redirect(auth.entra_logout_url(request.url_root.rstrip("/") + "/login"))
        except Exception:
            app.logger.exception("entra logout")
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
        out = _pm_call(lambda s: s.save_budget(payload))
        cache_mod.cache.mark_dirty()   # a budget change -> refresh the dashboard now
        return jsonify(out)
    except Exception as e:
        app.logger.exception("pm save_budget failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/pm/add", methods=["POST"])
def api_pm_add():
    denied = auth.gate("pm")           # only PM / Admin may bring a project in
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    if not payload.get("project_id"):
        return jsonify({"error": "project_id is required"}), 400
    try:
        out = _pm_call(lambda s: s.add_project(payload["project_id"], g.get("user")))
        cache_mod.cache.mark_dirty()   # new tracked project -> refresh the dashboard
        return jsonify(out)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.exception("pm add_project failed")
        return jsonify({"error": str(e)}), 500


# ── PM controls: author/edit a project's plan (schedule & progress) ───────────
@app.route("/plan")
def plan_page():
    return render_template("plan.html")


def _plan_service():
    return make_plan_service(demo=app.config["DEMO"])


def _plan_call(fn):
    svc = _plan_service()
    try:
        return fn(svc)
    finally:
        close = getattr(svc, "close", None)
        if close:
            close()


@app.route("/api/plan/projects")
def api_plan_projects():
    try:
        return jsonify(_plan_call(lambda s: s.list_projects()))
    except Exception as e:
        app.logger.exception("plan projects failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/plan/<int:pid>")
def api_plan_get(pid):
    try:
        return jsonify(_plan_call(lambda s: s.get_plan(pid)))
    except Exception as e:
        app.logger.exception("plan get failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/plan", methods=["POST"])
def api_plan_save():
    denied = auth.gate("pm")           # only PM / Admin may write the plan
    if denied:
        return denied
    payload = request.get_json(silent=True) or {}
    if not payload.get("project_id"):
        return jsonify({"error": "project_id is required"}), 400
    payload.setdefault("entered_by", g.get("user"))
    try:
        out = _plan_call(lambda s: s.save_plan(payload))
        cache_mod.cache.mark_dirty()   # a plan change -> refresh the dashboard now
        return jsonify(out)
    except Exception as e:
        app.logger.exception("plan save failed")
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
    payload = request.get_json(silent=True) or {}
    try:
        # Dashboard queries (exec/scorecard) go through the warm cache; everything
        # else runs live per request as before.
        if (not app.config["DEMO"]) and payload.get("query_id") in cache_mod.HOT_QUERIES:
            return _serve_dashboard(payload)
        result = _run_from_payload(payload)
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


if __name__ != "__main__":
    # Served under waitress/gunicorn (imported as a module, not run directly) — warm
    # the dashboard cache eagerly at boot so the first viewer after a restart gets an
    # instant board. The `python -m console_web.app --demo` path takes the __main__
    # branch below instead, so demo mode never starts a live cache thread.
    try:
        _ensure_cache()
    except Exception:
        app.logger.exception("dashboard cache failed to start at boot")


if __name__ == "__main__":
    main()
