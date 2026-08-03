"""
console_diag_itemloc_check.py — is the Item Location report hanging server-side, or is it the
browser? (2026-08-03)

Runs item_location LIVE for a single project and the full tracked scope, times each, and checks
the payload is valid JSON. READ-ONLY.

  * If this HANGS (never finishes) → the query itself is the problem (server-side); note which
    scope it hung on and Ctrl+C.
  * If it returns fast with valid JSON → the server is fine and the browser can't render the
    result (row volume / a front-end issue) — a different fix.

Run:  python console_diag_itemloc_check.py   → paste the output (or say where it hung).
"""
import time
import json
import math


def tracked():
    from console.infra.connections import console_connection
    c = console_connection()
    cur = c.cursor()
    cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent ORDER BY ProjectID")
    ids = [int(r[0]) for r in cur.fetchall()]
    c.close()
    return ids


def check(label, ids):
    from console_web.queries import LiveQueryService
    print(f"\n== {label} ({len(ids)} project(s)) ==", flush=True)
    s = LiveQueryService()
    t0 = time.perf_counter()
    r = s.run("item_location", ids)
    dt = time.perf_counter() - t0
    d = r.to_dict()
    rows = d["rows"]
    print(f"   server time : {dt:.2f}s", flush=True)
    print(f"   rows        : {len(rows)}")
    # strict JSON (no NaN/Infinity allowed) + native-type check (no default=str mask)
    try:
        payload = json.dumps(d, allow_nan=False)
        print(f"   JSON        : VALID, {len(payload):,} bytes")
    except (ValueError, TypeError) as e:
        print(f"   JSON        : *** INVALID -> {type(e).__name__}: {e}")
    # explicit NaN/Inf scan
    bad = []
    for i, row in enumerate(rows):
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                bad.append((i, k, v))
    print(f"   NaN/Inf     : {len(bad)} cell(s) {bad[:5]}")
    try:
        s.close()
    except Exception:
        pass


def main():
    ids = tracked()
    check("SINGLE project", ids[:1])
    check("FULL scope", ids)
    print("\nDone. If both returned fast with VALID JSON, the server is fine and it's the browser "
          "rendering the result — tell me and I'll page/trim the Item Location output. If it hung, "
          "say on which scope.")


if __name__ == "__main__":
    main()
