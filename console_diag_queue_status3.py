"""
console_diag_queue_status3.py — ROUND 3: engineering-release HISTORY per machine. (2026-11-16)
READ-ONLY: SELECTs only.

Round 2: tblEventLog logs queue releases ('Queue Engineering Release' 52 all-time, '... Release
Detail' 7,363, '... Pre-release' 578, '... Pre-release Detail' 20,274). On the tracked projects the
first 'Queue Engineering Release Detail' is 2025-03-07, yet the earliest tblMasterQueue.EngReleaseDate
there is 2025-08-21 — so tblMasterQueue probably keeps only the LATEST release, and a machine can be
released more than once. This round checks:

  A. what a release event's details look like (EventDetails is ntext -> CAST)
  B. per tracked machine: number of release / release-detail events, first and last event date,
     versus tblMasterQueue.EngReleaseDate
  C. are 'Detail' events per item / assembly (count per release click)?

Run:  python console_diag_queue_status3.py   ->  diag_queue_status3_<date>.txt beside it.
"""
import datetime as _dt
import os
import sys

IDS = [250005, 250161, 220154, 240033, 230219, 230127, 240088, 240154, 240218, 250250,
       240040, 240148, 250217, 260079, 250340, 260178, 260168, 250284, 230204, 250299]
IDL = ",".join(str(i) for i in IDS)
REL = ("'Queue Engineering Release', 'Queue Engineering Release Detail', "
       "'Queue Engineering Pre-release', 'Queue Engineering Pre-release Detail'")


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


def run(cur, title, sql, limit=200, width=26):
    print(f"\n-- {title}")
    try:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rws = cur.fetchall()
    except Exception as e:
        print(f"   err {type(e).__name__}: {str(e)[:200]}")
        return
    print("   " + " | ".join(str(c)[:width] for c in cols))
    for r in rws[:limit]:
        print("   " + " | ".join(str(x).replace("\n", " ")[:width] for x in r))
    if len(rws) > limit:
        print(f"   … {len(rws) - limit} more")
    if not rws:
        print("   (no rows)")


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       f"diag_queue_status3_{_dt.date.today():%Y%m%d}.txt")
    sys.stdout = Tee(out)
    print(f"console_diag_queue_status3 — {_dt.datetime.now():%Y-%m-%d %H:%M}")
    cur = eto_connect().cursor()

    rule("A. What release events look like (latest 30 on 250005 and 230219)")
    run(cur, "sample",
        f"SELECT TOP 30 ProjectID, SpecID, EventDescription, "
        f"CAST(EventDetails AS nvarchar(300)) details, RaisedByEmployee, Raised FROM tblEventLog "
        f"WHERE ProjectID IN (250005, 230219) AND EventDescription IN ({REL}) ORDER BY Raised DESC",
        width=70)
    run(cur, "SpecID populated on release events? (tracked projects)",
        f"SELECT EventDescription, COUNT(*) n, SUM(CASE WHEN SpecID IS NULL THEN 1 ELSE 0 END) no_spec "
        f"FROM tblEventLog WHERE ProjectID IN ({IDL}) AND EventDescription IN ({REL}) "
        f"GROUP BY EventDescription", width=40)

    rule("B. Per tracked real machine: release events vs tblMasterQueue.EngReleaseDate")
    run(cur, "per machine",
        f"SELECT mq.ProjectID, mq.SpecID, "
        f"SUM(CASE WHEN e.EventDescription = 'Queue Engineering Release' THEN 1 ELSE 0 END) rel_events, "
        f"SUM(CASE WHEN e.EventDescription = 'Queue Engineering Release Detail' THEN 1 ELSE 0 END) rel_detail, "
        f"COUNT(DISTINCT CASE WHEN e.EventDescription LIKE 'Queue Engineering Release%' "
        f"THEN CONVERT(date, e.Raised) END) rel_days, "
        f"MIN(CASE WHEN e.EventDescription LIKE 'Queue Engineering Release%' THEN e.Raised END) first_rel_event, "
        f"MAX(CASE WHEN e.EventDescription LIKE 'Queue Engineering Release%' THEN e.Raised END) last_rel_event, "
        f"mq.EngReleaseDate, "
        f"MIN(CASE WHEN e.EventDescription LIKE 'Queue Engineering Pre-release%' THEN e.Raised END) first_pre_event, "
        f"mq.EngPreReleasedate "
        f"FROM tblMasterQueue mq LEFT JOIN tblEventLog e ON e.ProjectID = mq.ProjectID AND e.SpecID = mq.SpecID "
        f"AND e.EventDescription IN ({REL}) "
        f"WHERE mq.ProjectID IN ({IDL}) AND mq.SpecID < 700 "
        f"GROUP BY mq.ProjectID, mq.SpecID, mq.EngReleaseDate, mq.EngPreReleasedate "
        f"HAVING COUNT(e.EventLogID) > 0 OR mq.EngReleaseDate IS NOT NULL ORDER BY mq.ProjectID, mq.SpecID",
        width=24)

    rule("C. Release clicks: detail events per (machine, minute) on tracked projects")
    run(cur, "distribution of detail events per click",
        f"SELECT TOP 40 ProjectID, SpecID, CONVERT(varchar(16), Raised, 120) minute, "
        f"SUM(CASE WHEN EventDescription = 'Queue Engineering Release Detail' THEN 1 ELSE 0 END) details, "
        f"SUM(CASE WHEN EventDescription = 'Queue Engineering Release' THEN 1 ELSE 0 END) headers "
        f"FROM tblEventLog WHERE ProjectID IN ({IDL}) AND EventDescription LIKE 'Queue Engineering Release%' "
        f"GROUP BY ProjectID, SpecID, CONVERT(varchar(16), Raised, 120) ORDER BY minute DESC")

    print(f"\nDone. Output also written to {out}")


if __name__ == "__main__":
    main()
