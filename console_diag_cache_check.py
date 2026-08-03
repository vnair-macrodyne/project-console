"""
console_diag_cache_check.py — confirm the perf caches are present and engaging (2026-08-03).

Runs scorecard THREE times per scope with a FRESH service each call (simulating separate
requests). With the cross-request TTL caches, call #1 is cold (~5s) and #2/#3 should be well
under a second. If all three are slow, the code being run does NOT have the fix (pull + restart).
READ-ONLY.

Run:  python console_diag_cache_check.py   → paste the output.
"""
import time


def tracked():
    from console.infra.connections import console_connection
    c = console_connection()
    cur = c.cursor()
    cur.execute("SELECT DISTINCT ProjectID FROM Reporting.vw_Console_BudgetCurrent ORDER BY ProjectID")
    ids = [int(r[0]) for r in cur.fetchall()]
    c.close()
    return ids


def main():
    import console_web.queries as q
    has = hasattr(q, "_FIN_CACHE") and hasattr(q, "_NC_CACHE")
    print(f"perf caches present in this code: {has}   (False = old code, pull + restart the app)\n")
    ids = tracked()
    one = ids[:1]
    for scope, label in [(one, "SINGLE project"), (ids, f"FULL {len(ids)} projects")]:
        print(f"== {label} ==")
        for i in range(3):
            s = q.LiveQueryService()
            t0 = time.perf_counter()
            s.run("scorecard", scope)
            print(f"   call {i+1}: {time.perf_counter()-t0:6.2f}s")
            try:
                s.close()
            except Exception:
                pass
    print("\nExpect: call 1 ~4-5s (cold), calls 2-3 well under 1s. If so, the caches work — the "
          "running APP just needs a restart to pick up the new code. In normal use the background "
          "daemon keeps them warm, so even call 1 is paid by the daemon, not a user.")


if __name__ == "__main__":
    main()
