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

from flask import Flask, jsonify, request, send_file, render_template
import io

from console_web.queries import make_service, catalogue, branding
from console_web import exporters

app = Flask(__name__)
app.config["DEMO"] = False


def _service():
    return make_service(demo=app.config["DEMO"])


def _run_from_payload(payload):
    payload = payload or {}
    query_id = payload.get("query_id")
    project_ids = payload.get("project_ids") or []
    date_from = payload.get("date_from") or None
    date_to = payload.get("date_to") or None
    svc = _service()
    try:
        return svc.run(query_id, project_ids, date_from=date_from, date_to=date_to)
    finally:
        close = getattr(svc, "close", None)
        if close:
            close()


@app.route("/")
def index():
    return render_template("index.html")


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
