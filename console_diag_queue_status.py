"""
console_diag_queue_status.py — where (if anywhere) does ETO record a machine's QUEUE STATUS /
release to manufacturing, and is the change DATED?  (2026-11-16)  READ-ONLY: SELECTs only.

Why: Peter wants engineering hours split into "before the machine queue is released to
manufacturing" vs after. That needs, per machine (ProjectID + SpecID), the DATE it was released.
Known so far: tblSpec.BudgetMfgRelease / RevisedMfgRelease / MfgBegin are near-empty (8% / 0% / 8%);
tblBOMReleaseHistory is per-part releases to procurement, not a machine-level release.
tblMasterQueue has only ever been read for ShipReleaseDate.

Sections
  A. every table/view whose name contains 'queue' (row counts + columns)
  B. columns anywhere named like queue / status / stage / phase / release / mfg / manufactur
  C. tblMasterQueue deep dive on the tracked projects: coverage of every column, value spread of
     low-cardinality columns, sample rows
  D. status / queue / stage lookup tables (tlkp*) — full contents
  E. history / log / audit tables that carry ProjectID or SpecID — do any record status changes?
  F. ETO procedures / views that reference tblMasterQueue (how ETO itself uses it)

Run (on a machine that reaches MACRO-ETO-SVR, e.g. vnair):
    python console_diag_queue_status.py
    python console_diag_queue_status.py --ids seeds/active_projects_2026-11-09.txt
Writes the same text to diag_queue_status_<date>.txt beside the script — send that file back.
"""
import argparse
import datetime as _dt
import os
import sys

DEFAULT_IDS = [250005, 250161, 220154, 240033, 230219, 230127, 240088, 240154, 240218, 250250,
               240040, 240148, 250217, 260079, 250340, 260178, 260168, 250284, 230204, 250299]
KEYWORDS = ("queue", "status", "stage", "phase", "release", "mfg", "manufactur")


class Tee:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def write(self, s):
        sys.__stdout__.write(s)
        self.f.write(s)

    def flush(self):
        sys.__stdout__.flush()
        self.f.flush()


def eto_connect():
    try:
        from console.infra.connections import eto_connection
        return eto_connection()
    except Exception:
        from console_store import eto_connection
        return eto_connection()


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def q(cur, sql, *a):
    cur.execute(sql, *a)
    cols = [d[0] for d in cur.description] if cur.description else []
    return cols, cur.fetchall()


def show(cols, rws, limit=40, width=28):
    if not cols:
        return
    print("   " + " | ".join(str(c)[:width] for c in cols))
    for r in rws[:limit]:
        print("   " + " | ".join(str(x)[:width] for x in r))
    if len(rws) > limit:
        print(f"   … {len(rws) - limit} more rows")
    if not rws:
        print("   (no rows)")


def objects(cur):
    _, r = q(cur, "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES")
    return {n: t for n, t in r}


def cols_of(cur, obj):
    _, r = q(cur, "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                  "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION", obj)
    return r


def count(cur, obj, where="", *a):
    try:
        _, r = q(cur, f"SELECT COUNT(*) FROM [{obj}] {where}", *a)
        return r[0][0]
    except Exception as e:
        return f"err {type(e).__name__}"


def load_ids(path):
    if not path:
        return DEFAULT_IDS
    out = []
    for line in open(path, encoding="utf-8-sig"):
        tok = line.split(",")[0].strip()
        if tok.isdigit():
            out.append(int(tok))
    return list(dict.fromkeys(out)) or DEFAULT_IDS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", help="file with one column of project numbers (default: the 20 tracked)")
    args = ap.parse_args()
    ids = load_ids(args.ids)
    idlist = ",".join(str(i) for i in ids)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       f"diag_queue_status_{_dt.date.today():%Y%m%d}.txt")
    sys.stdout = Tee(out)
    print(f"console_diag_queue_status — {_dt.datetime.now():%Y-%m-%d %H:%M}  ({len(ids)} projects)")
    print("projects:", idlist)

    eto = eto_connect()
    cur = eto.cursor()
    objs = objects(cur)

    # ── A ─────────────────────────────────────────────────────────────────────────────────────
    rule("A. Tables / views with 'queue' in the name")
    qobjs = sorted(n for n in objs if "queue" in n.lower())
    for n in qobjs:
        c = cols_of(cur, n)
        print(f"\n  {n}  ({objs[n]}, rows={count(cur, n)})")
        print("   cols: " + ", ".join(f"{a}:{b}" for a, b in c))
    if not qobjs:
        print("  (none)")

    # ── B ─────────────────────────────────────────────────────────────────────────────────────
    rule("B. Columns anywhere named like " + "/".join(KEYWORDS))
    like = " OR ".join(f"LOWER(c.COLUMN_NAME) LIKE '%{k}%'" for k in KEYWORDS)
    cols, r = q(cur, "SELECT t.TABLE_TYPE, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE "
                     "FROM INFORMATION_SCHEMA.COLUMNS c JOIN INFORMATION_SCHEMA.TABLES t "
                     "ON t.TABLE_NAME = c.TABLE_NAME AND t.TABLE_SCHEMA = c.TABLE_SCHEMA "
                     f"WHERE ({like}) ORDER BY t.TABLE_TYPE, c.TABLE_NAME, c.COLUMN_NAME")
    show(cols, r, limit=400, width=40)

    # ── C ─────────────────────────────────────────────────────────────────────────────────────
    for mq in [n for n in qobjs if objs[n] == "BASE TABLE"] or ["tblMasterQueue"]:
        rule(f"C. {mq} — tracked projects only")
        c = cols_of(cur, mq)
        names = [a for a, _ in c]
        if not names:
            print("  (table not found)")
            continue
        where = f"WHERE ProjectID IN ({idlist})" if "ProjectID" in names else ""
        total = count(cur, mq, where)
        print(f"  rows (tracked): {total}   key cols present: "
              f"{[k for k in ('ProjectID', 'SpecID', 'StatusID', 'QueueID') if k in names]}")
        if "ProjectID" in names:
            _, r = q(cur, f"SELECT COUNT(DISTINCT ProjectID) FROM [{mq}] {where}")
            print(f"  tracked projects with rows: {r[0][0]} of {len(ids)}")
            if "SpecID" in names:
                _, r = q(cur, f"SELECT COUNT(*) FROM (SELECT DISTINCT ProjectID, SpecID FROM [{mq}] {where}) x")
                _, r2 = q(cur, f"SELECT COUNT(*) FROM tblSpec WHERE ProjectID IN ({idlist}) AND SpecID < 700")
                print(f"  machines with rows: {r[0][0]}   (real machines on tracked projects: {r2[0][0]})")
        print("\n  column coverage (filled / rows, min, max, distinct):")
        for name, dtype in c:
            try:
                _, r = q(cur, f"SELECT SUM(CASE WHEN [{name}] IS NOT NULL THEN 1 ELSE 0 END), "
                              f"MIN([{name}]), MAX([{name}]), COUNT(DISTINCT [{name}]) FROM [{mq}] {where}")
                f, mn, mx, nd = r[0]
                print(f"   {name:32} {dtype:10} {f}/{total}  min={str(mn)[:19]}  max={str(mx)[:19]}  distinct={nd}")
                if nd and nd <= 15 and dtype not in ("datetime", "date", "datetime2", "smalldatetime"):
                    _, vv = q(cur, f"SELECT [{name}], COUNT(*) FROM [{mq}] {where} GROUP BY [{name}] ORDER BY 2 DESC")
                    print("        values: " + "; ".join(f"{v!s}={n}" for v, n in vv))
            except Exception as e:
                print(f"   {name:32} {dtype:10} err {type(e).__name__}")
        for pid in (250005, 230219):
            if "ProjectID" in names:
                cl, r = q(cur, f"SELECT TOP 15 * FROM [{mq}] WHERE ProjectID = ?", pid)
                print(f"\n  sample rows, project {pid}:")
                show(cl, r, limit=15, width=18)

    # ── D ─────────────────────────────────────────────────────────────────────────────────────
    rule("D. Lookup tables for status / queue / stage")
    lk = sorted(n for n in objs if n.lower().startswith("tlkp")
                and any(k in n.lower() for k in ("status", "queue", "stage", "phase")))
    for n in lk:
        cl, r = q(cur, f"SELECT TOP 60 * FROM [{n}]")
        print(f"\n  {n}  (rows={count(cur, n)})")
        show(cl, r, limit=60, width=24)
    if not lk:
        print("  (none)")

    # ── E ─────────────────────────────────────────────────────────────────────────────────────
    rule("E. History / log / audit tables keyed to a project or machine")
    hist = sorted(n for n in objs if objs[n] == "BASE TABLE"
                  and any(k in n.lower() for k in ("history", "log", "audit", "change")))
    for n in hist:
        names = [a for a, _ in cols_of(cur, n)]
        if not ({"ProjectID", "SpecID"} & set(names)):
            continue
        hits = [a for a in names if any(k in a.lower() for k in KEYWORDS + ("date",))]
        rc = count(cur, n, f"WHERE ProjectID IN ({idlist})") if "ProjectID" in names else count(cur, n)
        print(f"\n  {n}  rows(tracked)={rc}")
        print("   cols: " + ", ".join(names))
        print("   status/date-ish: " + ", ".join(hits))
    # ── F ─────────────────────────────────────────────────────────────────────────────────────
    rule("F. ETO procedures / views / functions that mention MasterQueue or queue status")
    try:
        cl, r = q(cur, "SELECT o.type_desc, o.name FROM sys.sql_modules m JOIN sys.objects o "
                       "ON o.object_id = m.object_id WHERE m.definition LIKE '%MasterQueue%' "
                       "OR m.definition LIKE '%QueueStatus%' ORDER BY o.type_desc, o.name")
        show(cl, r, limit=200, width=60)
    except Exception as e:
        print(f"  err {e}")

    eto.close()
    print(f"\nDone. Output also written to {out}")


if __name__ == "__main__":
    main()
