"""
console_diag_phase_model.py — project PHASE MODEL probe. (2026-11-20)
READ-ONLY: SELECTs only.

Goal: agree the phase list for a machine (Sales -> Engineering -> Release -> Procurement ->
Manufacturing -> Shipping -> Accounting -> Closed) and, for each phase, which ETO signal marks
its start and end and how reliably it is filled in. Earlier probes covered ACTIVE projects only;
this one looks portfolio-wide, including machines that have gone all the way to Closed.

  A. tblMasterQueue: fill rate of every column (all machines, and by current queue)
  B. current queue distribution, portfolio-wide (vwQueueManagement)
  C. queue-release events in tblEventLog by type and year
  D. hour departments in use (tlkpHourTypes.HourDepartment) with hours
  E. per-machine milestone spine for finished machines (Shipping/Accounting/Closed queues)
  F. median days between consecutive milestones, from E

Run:  python console_diag_phase_model.py   ->  diag_phase_model_<date>.txt beside it.
"""
import datetime as _dt
import os
import statistics
import sys

FINISHED = "('Shipping', 'Accounting', 'Closed')"


class Tee:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def write(self, s):
        sys.__stdout__.write(s); self.f.write(s)

    def flush(self):
        sys.__stdout__.flush(); self.f.flush()


def eto_connect():
    try:
        from console.infra.connections import eto_connection
        return eto_connection()
    except Exception:
        from console_store import eto_connection
        return eto_connection()


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def fetch(cur, sql):
    cur.execute(sql)
    return [d[0] for d in cur.description], cur.fetchall()


def run(cur, title, sql, limit=200, width=26):
    print(f"\n-- {title}")
    try:
        cols, rws = fetch(cur, sql)
    except Exception as e:
        print(f"   err {type(e).__name__}: {str(e)[:300]}")
        return [], []
    print("   " + " | ".join(str(c)[:width] for c in cols))
    for r in rws[:limit]:
        print("   " + " | ".join(str(x).replace("\n", " ")[:width] for x in r))
    if len(rws) > limit:
        print(f"   … {len(rws) - limit} more")
    if not rws:
        print("   (no rows)")
    return cols, rws


SPINE = f"""
WITH m AS (
    SELECT qm.ProjectID, qm.SpecID, qm.CurrentQueue
    FROM vwQueueManagement qm
    WHERE qm.CurrentQueue IN {FINISHED} AND qm.SpecID < 700
),
ev AS (
    SELECT e.ProjectID, e.SpecID,
        MIN(CASE WHEN e.EventDescription LIKE 'Queue Sales Release%'               THEN e.Raised END) sales_rel,
        MIN(CASE WHEN e.EventDescription LIKE 'Queue Engineering Pre-release%'     THEN e.Raised END) pre_rel_first,
        MIN(CASE WHEN e.EventDescription LIKE 'Queue Engineering Release%'         THEN e.Raised END) eng_rel_first,
        MAX(CASE WHEN e.EventDescription LIKE 'Queue Engineering Release%'         THEN e.Raised END) eng_rel_last,
        MIN(CASE WHEN e.EventDescription LIKE 'Queue Manufacturing Release%'       THEN e.Raised END) mfg_rel,
        MIN(CASE WHEN e.EventDescription LIKE 'Queue Shipping Release%'            THEN e.Raised END) ship_rel,
        MIN(CASE WHEN e.EventDescription LIKE 'Queue Accounting Release%'          THEN e.Raised END) acc_rel,
        MIN(CASE WHEN e.EventDescription LIKE 'Queue Closing Release%'             THEN e.Raised END) close_rel
    FROM tblEventLog e
    JOIN m ON m.ProjectID = e.ProjectID AND m.SpecID = e.SpecID
    WHERE e.EventDescription LIKE 'Queue %'
    GROUP BY e.ProjectID, e.SpecID
),
hrs AS (
    SELECT tc.ProjectID, tc.SpecID,
        MIN(CASE WHEN ht.HourDepartment = 'Engineering'  THEN tc.TimeDate END) eng_hrs_first,
        MAX(CASE WHEN ht.HourDepartment = 'Engineering'  THEN tc.TimeDate END) eng_hrs_last,
        MIN(CASE WHEN ht.HourDepartment <> 'Engineering' THEN tc.TimeDate END) other_hrs_first,
        MAX(CASE WHEN ht.HourDepartment <> 'Engineering' THEN tc.TimeDate END) other_hrs_last
    FROM tblTimecards tc
    JOIN m ON m.ProjectID = tc.ProjectID AND m.SpecID = tc.SpecID
    LEFT JOIN tlkpHourTypes ht ON ht.HourType = tc.HourType
    GROUP BY tc.ProjectID, tc.SpecID
),
bom AS (
    SELECT h.ProjectID, MIN(h.ReleasedDateTime) bom_first, MAX(h.ReleasedDateTime) bom_last
    FROM tblBOMReleaseHistory h WHERE h.ProjectID IN (SELECT ProjectID FROM m) GROUP BY h.ProjectID
),
po AS (
    SELECT p.ProjectID, MIN(p.PurchaseDate) po_first
    FROM vwPurchaseOrderHeader p WHERE p.ProjectID IN (SELECT ProjectID FROM m) GROUP BY p.ProjectID
)
SELECT TOP 80 m.ProjectID, m.SpecID, m.CurrentQueue,
    sp.SDate order_date, ev.sales_rel, ev.pre_rel_first, hrs.eng_hrs_first,
    ev.eng_rel_first, bom.bom_first, po.po_first, ev.eng_rel_last, hrs.eng_hrs_last,
    ev.mfg_rel, hrs.other_hrs_first, hrs.other_hrs_last, ev.ship_rel, ev.acc_rel, ev.close_rel
FROM m
JOIN tblSpec sp ON sp.ProjectID = m.ProjectID AND sp.SpecID = m.SpecID
LEFT JOIN ev  ON ev.ProjectID  = m.ProjectID AND ev.SpecID  = m.SpecID
LEFT JOIN hrs ON hrs.ProjectID = m.ProjectID AND hrs.SpecID = m.SpecID
LEFT JOIN bom ON bom.ProjectID = m.ProjectID
LEFT JOIN po  ON po.ProjectID  = m.ProjectID
ORDER BY sp.SDate DESC
"""

ORDER = ["order_date", "sales_rel", "pre_rel_first", "eng_hrs_first", "eng_rel_first", "bom_first",
         "po_first", "eng_rel_last", "eng_hrs_last", "mfg_rel", "other_hrs_first", "other_hrs_last",
         "ship_rel", "acc_rel", "close_rel"]


def _day(x):
    if x is None:
        return None
    if isinstance(x, _dt.datetime):
        return x.date()
    return x


def summarise(cols, rows):
    idx = {c: i for i, c in enumerate(cols)}
    print(f"\n   machines: {len(rows)}")
    print("   fill rate per milestone:")
    for c in ORDER:
        n = sum(1 for r in rows if r[idx[c]] is not None)
        print(f"     {c:16} {n:3}/{len(rows)}")
    print("\n   days from order_date (median / min / max, where both set):")
    for c in ORDER[1:]:
        gaps = []
        for r in rows:
            a, b = _day(r[idx["order_date"]]), _day(r[idx[c]])
            if a is not None and b is not None:
                gaps.append((b - a).days)
        if gaps:
            print(f"     {c:16} n={len(gaps):3}  median {statistics.median(gaps):7.0f}  "
                  f"min {min(gaps):6}  max {max(gaps):6}")
        else:
            print(f"     {c:16} n=  0")


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       f"diag_phase_model_{_dt.date.today():%Y%m%d}.txt")
    sys.stdout = Tee(out)
    print(f"console_diag_phase_model — {_dt.datetime.now():%Y-%m-%d %H:%M}")
    cur = eto_connect().cursor()

    rule("A. tblMasterQueue: fill rate of every column")
    try:
        _, colrows = fetch(cur, "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                                "WHERE TABLE_NAME = 'tblMasterQueue' ORDER BY ORDINAL_POSITION")
    except Exception as e:
        print(f"   err {type(e).__name__}: {str(e)[:300]}")
        colrows = []
    print("   columns: " + ", ".join(f"{c}({t})" for c, t in colrows))
    parts = []
    for c, t in colrows:
        if t == "bit":
            parts.append(f"SUM(CASE WHEN mq.[{c}] = 1 THEN 1 ELSE 0 END) [{c}]")
        elif t in ("datetime", "date", "smalldatetime", "datetime2"):
            parts.append(f"SUM(CASE WHEN mq.[{c}] IS NOT NULL THEN 1 ELSE 0 END) [{c}]")
    if parts:
        sel = ", ".join(parts)
        run(cur, "all machines (bit = count true, date = count filled)",
            f"SELECT COUNT(*) machines, {sel} FROM tblMasterQueue mq", width=14)
        run(cur, "by current queue",
            f"SELECT qm.CurrentQueue, COUNT(*) machines, {sel} FROM tblMasterQueue mq "
            f"JOIN vwQueueManagement qm ON qm.ProjectID = mq.ProjectID AND qm.SpecID = mq.SpecID "
            f"GROUP BY qm.CurrentQueue ORDER BY COUNT(*) DESC", width=14)

    rule("B. Current queue, portfolio-wide")
    run(cur, "machines per queue (real machines SpecID < 700)",
        "SELECT CurrentQueue, QueueStatus, COUNT(*) machines, COUNT(DISTINCT ProjectID) projects "
        "FROM vwQueueManagement WHERE SpecID < 700 GROUP BY CurrentQueue, QueueStatus "
        "ORDER BY COUNT(*) DESC", width=30)

    rule("C. Queue-release events by type and year")
    run(cur, "tblEventLog 'Queue %'",
        "SELECT EventDescription, YEAR(Raised) yr, COUNT(*) n FROM tblEventLog "
        "WHERE EventDescription LIKE 'Queue %' GROUP BY EventDescription, YEAR(Raised) "
        "ORDER BY EventDescription, yr", limit=400, width=44)

    rule("D. Hour departments in use")
    run(cur, "hours by HourDepartment",
        "SELECT ht.HourDepartment, COUNT(DISTINCT ht.HourType) hour_types, "
        "CAST(SUM(tc.HourTime) AS int) hours, MIN(tc.TimeDate) first, MAX(tc.TimeDate) last "
        "FROM tblTimecards tc LEFT JOIN tlkpHourTypes ht ON ht.HourType = tc.HourType "
        "GROUP BY ht.HourDepartment ORDER BY SUM(tc.HourTime) DESC", width=30)

    rule("E. Milestone spine, finished machines (latest 80 by order date)")
    cols, rows = run(cur, "per machine", SPINE, limit=80, width=11)

    rule("F. Milestone fill rate and timing, from E")
    if rows:
        summarise(cols, rows)

    print(f"\nDone. Output also written to {out}")


if __name__ == "__main__":
    main()
