"""
console_diag_queue_status2.py — ROUND 2 on machine queue / release to manufacturing. (2026-11-16)
READ-ONLY: SELECTs only.

Round 1 (console_diag_queue_status.py) found tblMasterQueue: one row per machine (ProjectID+SpecID)
with a flag + date per queue release — Sales, EngPreRelease, EngRelease, Gen, Mfg, Acc, Closing, Ship.
On the 20 tracked projects: EngReleaseDate 29/158 rows, EngPreReleasedate 50/158, MfgReleaseDate 0.
Reading: a machine sits in the ENGINEERING queue until EngRelease moves it to MANUFACTURING
(vwQueueManufacturing carries EngRelease; vwQueueShipping carries MfgRelease) — so EngReleaseDate
is Peter's "released to manufacturing" cut-off. This round confirms that and checks history.

  A. Queue names ETO shows: distinct QueueStatus / QueueDescription (vwQueueSummary) and
     ReleaseStatus / ReleaseDescription / CurrentQueue (vwQueueManagement) on tracked projects
  B. Per REAL machine (SpecID < 700): current queue + EngPreRelease / EngRelease flags and dates
  C. Coverage per project: machines, pre-released, released
  D. Is release HISTORY kept? tblEventLog event types on tracked projects, and any events
     mentioning release / queue (re-release, un-release, date changes)
  E. Preview of Peter's KPI: Engineering-department hours booked before vs after each machine's
     EngReleaseDate (machines with no release yet count as 'before')

Run:  python console_diag_queue_status2.py   →  writes diag_queue_status2_<date>.txt beside it.
"""
import datetime as _dt
import os
import sys

IDS = [250005, 250161, 220154, 240033, 230219, 230127, 240088, 240154, 240218, 250250,
       240040, 240148, 250217, 260079, 250340, 260178, 260168, 250284, 230204, 250299]
IDL = ",".join(str(i) for i in IDS)


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
        print("   " + " | ".join(str(x)[:width] for x in r))
    if len(rws) > limit:
        print(f"   … {len(rws) - limit} more")
    if not rws:
        print("   (no rows)")


def main():
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       f"diag_queue_status2_{_dt.date.today():%Y%m%d}.txt")
    sys.stdout = Tee(out)
    print(f"console_diag_queue_status2 — {_dt.datetime.now():%Y-%m-%d %H:%M}")
    cur = eto_connect().cursor()

    rule("A. Queue names as ETO shows them (tracked projects)")
    run(cur, "vwQueueSummary: QueueStatus / QueueDescription",
        f"SELECT QueueStatus, QueueDescription, COUNT(*) machines FROM vwQueueSummary "
        f"WHERE ProjectID IN ({IDL}) GROUP BY QueueStatus, QueueDescription ORDER BY QueueStatus")
    run(cur, "vwQueueManagement: ReleaseStatus / ReleaseDescription / CurrentQueue",
        f"SELECT ReleaseStatus, ReleaseDescription, QueueStatus, CurrentQueue, COUNT(*) machines "
        f"FROM vwQueueManagement WHERE ProjectID IN ({IDL}) "
        f"GROUP BY ReleaseStatus, ReleaseDescription, QueueStatus, CurrentQueue ORDER BY ReleaseStatus, QueueStatus")
    run(cur, "VwSpecQueueSummary: Status / Description (all)",
        "SELECT Status, Description, COUNT(*) n FROM VwSpecQueueSummary GROUP BY Status, Description ORDER BY Status")

    rule("B. Real machines (SpecID < 700): current queue + engineering release flags and dates")
    run(cur, "per machine",
        f"SELECT mq.ProjectID, mq.SpecID, s.SDescription, qs.QueueDescription, qm.CurrentQueue, "
        f"CAST(mq.EngPreRelease AS int) EngPre, mq.EngPreReleasedate, "
        f"CAST(mq.EngRelease AS int) EngRel, mq.EngReleaseDate, "
        f"CAST(mq.MfgRelease AS int) MfgRel, mq.SalesReleaseDate "
        f"FROM tblMasterQueue mq "
        f"LEFT JOIN tblSpec s ON s.ProjectID = mq.ProjectID AND s.SpecID = mq.SpecID "
        f"LEFT JOIN vwQueueSummary qs ON qs.ProjectID = mq.ProjectID AND qs.SpecID = mq.SpecID "
        f"LEFT JOIN vwQueueManagement qm ON qm.ProjectID = mq.ProjectID AND qm.SpecID = mq.SpecID "
        f"WHERE mq.ProjectID IN ({IDL}) AND mq.SpecID < 700 ORDER BY mq.ProjectID, mq.SpecID", limit=150, width=22)

    rule("C. Coverage per project (real machines)")
    run(cur, "per project",
        f"SELECT ProjectID, COUNT(*) machines, "
        f"SUM(CASE WHEN EngPreRelease = 1 THEN 1 ELSE 0 END) pre_flag, "
        f"SUM(CASE WHEN EngPreReleasedate IS NOT NULL THEN 1 ELSE 0 END) pre_dated, "
        f"SUM(CASE WHEN EngRelease = 1 THEN 1 ELSE 0 END) rel_flag, "
        f"SUM(CASE WHEN EngReleaseDate IS NOT NULL THEN 1 ELSE 0 END) rel_dated, "
        f"SUM(CASE WHEN MfgRelease = 1 THEN 1 ELSE 0 END) mfg_flag, "
        f"MIN(EngReleaseDate) first_rel, MAX(EngReleaseDate) last_rel "
        f"FROM tblMasterQueue WHERE ProjectID IN ({IDL}) AND SpecID < 700 GROUP BY ProjectID ORDER BY ProjectID")
    run(cur, "all projects, by year of EngReleaseDate (is this a long-standing practice?)",
        "SELECT YEAR(EngReleaseDate) yr, COUNT(*) machines_released, "
        "SUM(CASE WHEN MfgReleaseDate IS NOT NULL THEN 1 ELSE 0 END) also_mfg_released "
        "FROM tblMasterQueue WHERE EngReleaseDate IS NOT NULL GROUP BY YEAR(EngReleaseDate) ORDER BY yr")

    rule("D. Is release history kept? tblEventLog")
    run(cur, "event types on tracked projects (top 60)",
        f"SELECT TOP 60 EventDescription, COUNT(*) n, MIN(Raised) first_raised, MAX(Raised) last_raised "
        f"FROM tblEventLog WHERE ProjectID IN ({IDL}) GROUP BY EventDescription ORDER BY n DESC", width=40)
    run(cur, "events mentioning release / queue (top 40 types, all projects)",
        "SELECT TOP 40 EventDescription, COUNT(*) n FROM tblEventLog "
        "WHERE EventDescription LIKE '%releas%' OR EventDescription LIKE '%queue%' "
        "OR EventDetails LIKE '%queue%' GROUP BY EventDescription ORDER BY n DESC", width=50)
    run(cur, "sample release/queue events, 250005 and 230219",
        "SELECT TOP 40 ProjectID, SpecID, EventDescription, LEFT(EventDetails, 120) details, "
        "RaisedByEmployee, Raised FROM tblEventLog WHERE ProjectID IN (250005, 230219) "
        "AND (EventDescription LIKE '%releas%' OR EventDescription LIKE '%queue%' "
        "OR EventDetails LIKE '%releas%' OR EventDetails LIKE '%queue%') ORDER BY Raised DESC",
        width=60)

    rule("E. Preview: Engineering-department hours before vs after each machine's EngReleaseDate")
    run(cur, "by project (HourDepartment = 'Engineering'; real machines; no release yet = before)",
        f"SELECT tc.ProjectID, "
        f"CAST(SUM(CASE WHEN mq.EngReleaseDate IS NULL OR tc.TimeDate < mq.EngReleaseDate "
        f"THEN tc.HourTime ELSE 0 END) AS decimal(12,1)) eng_hrs_before, "
        f"CAST(SUM(CASE WHEN mq.EngReleaseDate IS NOT NULL AND tc.TimeDate >= mq.EngReleaseDate "
        f"THEN tc.HourTime ELSE 0 END) AS decimal(12,1)) eng_hrs_after, "
        f"CAST(SUM(tc.HourTime) AS decimal(12,1)) eng_hrs_total "
        f"FROM tblTimecards tc "
        f"JOIN tlkpHourTypes ht ON ht.HourType = tc.HourType "
        f"LEFT JOIN tblMasterQueue mq ON mq.ProjectID = tc.ProjectID AND mq.SpecID = tc.SpecID "
        f"WHERE tc.ProjectID IN ({IDL}) AND tc.SpecID < 700 AND ht.HourDepartment = 'Engineering' "
        f"GROUP BY tc.ProjectID ORDER BY tc.ProjectID")
    run(cur, "HourDepartment values (to confirm 'Engineering' is the right filter)",
        "SELECT HourDepartment, COUNT(*) hour_types FROM tlkpHourTypes GROUP BY HourDepartment ORDER BY 1")

    print(f"\nDone. Output also written to {out}")


if __name__ == "__main__":
    main()
