"""
console_diag_budget_reconcile.py — why the /pm discipline budget and the machine × discipline
breakdown disagree on Engineering vs Manufacturing.  (2026-09-06)  READ-ONLY.

The top /pm table (EtoBudgetDAO) anchors Admin/Eng/Mfg to ETO's rolled-up estimate view
(vwProjectActualsVSEstimates). The machine table sums raw tblSpecHours through our HourType→
discipline map. Totals match; the Eng/Mfg boundary differs by ~160 hrs on 210065. This finds the
HourType(s) responsible so we can fix the crosswalk (after which BOTH tables + the dashboard agree).

Run:  python console_diag_budget_reconcile.py [projectID]   (default 210065)
Paste the whole output.
"""
import sys

PID = sys.argv[1] if len(sys.argv) > 1 else "210065"
_ENG = ("Mechanical Engineering", "Hydraulic Engineering", "Electrical Engineering")


def eto_connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception:
        import os, pyodbc
        from console_config import TENANT
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
              f"Database={TENANT.eto_database};")
        cs += ("Trusted_Connection=yes;" if TENANT.use_windows_auth
               else f"UID={os.environ.get('ETO_USER')};PWD={os.environ.get('ETO_PWD')};")
        return pyodbc.connect(cs)


def console_connect():
    for imp in ("from console_store import console_connection as cc",
                "from console.infra.connections import console_connection as cc"):
        try:
            ns = {}
            exec(imp, ns)
            return ns["cc"]()
        except Exception:
            continue
    return None


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def rows(cur, sql, *a):
    cur.execute(sql, *a)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def load_htmap(eto):
    """The exact {HourType: discipline} the app uses (store table, else derived from ETO)."""
    try:
        from console.domain.hourtype_map import HourTypeDisciplineDAO
        cc = console_connect()
        dao = HourTypeDisciplineDAO(cc) if cc else None
        m = (dao.load_map() if dao else None) or HourTypeDisciplineDAO.derive_from_eto(eto)
        return {int(k): v for k, v in m.items()}, ("store" if (dao and dao.load_map()) else "derived")
    except Exception as e:
        print("  (could not load app hourtype_map:", e, "— falling back to blank)")
        return {}, "none"


def bucket(disc):
    if disc == "Project Management":
        return "Admin"
    if disc in _ENG:
        return "Eng"
    if disc == "Manufacturing":
        return "Mfg"
    return "Other"


def main():
    eto = eto_connect(); cur = eto.cursor()
    htmap, src = load_htmap(eto)
    print(f"Project {PID} — hourtype_map source: {src} ({len(htmap)} hourtypes)")

    rule("A. ETO rolled-up estimate view (what the /pm discipline table anchors to)")
    _, v = rows(cur, "SELECT ISNULL(EstAdminHours,0), ISNULL(EstEngHours,0), ISNULL(EstMfgHours,0) "
                     "FROM dbo.vwProjectActualsVSEstimates WHERE ProjectID = ?", PID)
    if v:
        a, e, m = [float(x) for x in v[0]]
        print(f"  EstAdminHours={a:,.2f}  EstEngHours={e:,.2f}  EstMfgHours={m:,.2f}  total={a+e+m:,.2f}")
    else:
        a = e = m = 0.0
        print("  (no row in vwProjectActualsVSEstimates)")

    rule("B. tblSpecHours by HourType → our discipline (what the machine table sums)")
    _, det = rows(cur, """
        SELECT s.HourType, h.HourDescription, CAST(SUM(s.Hours) AS decimal(16,2)) AS Hours
        FROM dbo.tblSpecHours s
        LEFT JOIN dbo.tlkpHourTypes h ON h.HourType = s.HourType
        WHERE s.ProjectID = ?
        GROUP BY s.HourType, h.HourDescription
        ORDER BY SUM(s.Hours) DESC""", PID)
    bkt = {"Admin": 0.0, "Eng": 0.0, "Mfg": 0.0, "Other": 0.0}
    print(f"  {'HT':>4} {'HourDescription':34} {'Hours':>10}  {'our discipline':26} bucket")
    for ht, hd, hrs in det:
        disc = htmap.get(int(ht) if ht is not None else -1, "Other")
        b = bucket(disc)
        bkt[b] += float(hrs or 0)
        print(f"  {str(ht):>4} {str(hd)[:34]:34} {float(hrs or 0):>10,.2f}  {disc:26} {b}")

    rule("C. Bucket comparison — VIEW vs our crosswalk (the gap to close)")
    print(f"  {'bucket':8} {'ETO view':>12} {'our sum':>12} {'delta (view - ours)':>22}")
    for b, vv in (("Admin", a), ("Eng", e), ("Mfg", m)):
        print(f"  {b:8} {vv:>12,.2f} {bkt[b]:>12,.2f} {vv - bkt[b]:>22,.2f}")
    print(f"  {'Other':8} {'—':>12} {bkt['Other']:>12,.2f}")
    print("\n  Read: the bucket with a POSITIVE 'view - ours' delta has hours ETO counts there that our "
          "crosswalk sends elsewhere (the negative-delta bucket). Find the HourType in section B whose "
          "'our discipline' looks wrong for its description — that's the crosswalk row to fix. After the "
          "fix, our sum == the view and both /pm tables reconcile.")
    eto.close()


if __name__ == "__main__":
    main()
