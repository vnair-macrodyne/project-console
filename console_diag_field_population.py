"""
console_diag_field_population.py — measure how well teams are MAINTAINING key ETO fields.
(2026-09-05)  READ-ONLY.  This is the query logic for the planned "Data Completeness" report.

For a curated set of fields that teams are supposed to enter, it reports the POPULATION RATE
(filled / total, %) — scoped to ACTIVE projects (last charge within 12 months) so long-dead jobs
don't mask a current gap. Sparsely-populated fields are the point: a low rate means the team isn't
entering it, not that the field is missing.

Run:  python console_diag_field_population.py
Paste the whole output.
"""

# owner (team), table, column, human label, scope: 'active' (project-scoped) | 'all'
FIELDS = [
    ("Project Mgmt", "tblProjects",              "PDelivery",           "Project delivery date",        "active_self"),
    ("Project Mgmt", "tblProjects",              "PercentCompleteDate", "Project %-complete date",       "active_self"),
    ("Engineering",  "tblSpec",                  "BudgetShipRelease",   "Machine ship-release (budget)", "active"),
    ("Engineering",  "tblSpec",                  "BudgetEngRelease",    "Machine eng-release (budget)",  "active"),
    ("Engineering",  "tblSpec",                  "BudgetMfgRelease",    "Machine mfg-release (budget)",  "active"),
    ("Engineering",  "tblSpec",                  "MfgBegin",            "Machine mfg begin",             "active"),
    ("Engineering",  "tblSpec",                  "PercentCompleteDate", "Machine %-complete date",       "active"),
    ("Engineering",  "tblEngItemMaster",         "EstimatedLeadTime",   "Item lead time (days)",         "all"),
    ("Engineering",  "tblEngItemMaster",         "ItemCertifiedPrints", "Item certified-prints flag",    "all"),
    ("Purchasing",   "tblPurchaseOrderDetails",  "DateRequired",        "PO line need-by date",          "active"),
    ("Purchasing",   "tblPurchaseOrderDetails",  "DateRevised",         "PO line revised need-by",       "active"),
    ("Purchasing",   "tblPurchaseOrderDetails",  "PurchaseOrderDetailCustom5", "PO line custom-5 date",   "active"),
    ("Production",   "tblProcessScheduleHeader", "StartDate",           "Schedule start",                "active"),
    ("Production",   "tblProcessScheduleHeader", "FinalRequiredDate",   "Schedule final-required",       "active"),
    ("Production",   "tblProcessScheduleHeader", "CompletionDate",      "Schedule completion",           "active"),
]

ACTIVE = "SELECT ProjectID FROM dbo.tblProjects WHERE PLast >= DATEADD(month, -12, GETDATE())"


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


def col_type(cur, table, col):
    cur.execute("SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_NAME = ? AND COLUMN_NAME = ?", table, col)
    r = cur.fetchone()
    return (r[0] if r else None)


def filled_pred(col, dtype):
    d = (dtype or "").lower()
    if d in ("datetime", "date", "datetime2", "smalldatetime"):
        return f"[{col}] IS NOT NULL"
    if d in ("bit",):
        return f"[{col}] IS NOT NULL"
    if d in ("int", "bigint", "smallint", "tinyint", "decimal", "numeric", "float", "real", "money"):
        return f"[{col}] IS NOT NULL AND [{col}] <> 0"
    return f"[{col}] IS NOT NULL AND LTRIM(RTRIM(CAST([{col}] AS nvarchar(4000)))) <> ''"


def scope_clause(table, scope):
    if scope == "active_self":                       # the table IS tblProjects
        return "WHERE PLast >= DATEADD(month, -12, GETDATE())"
    if scope == "active":                            # project-scoped table
        return f"WHERE ProjectID IN ({ACTIVE})"
    return ""                                        # 'all'


def main():
    eto = eto_connect(); cur = eto.cursor()
    print(f"{'Owner':13} {'Field':30} {'Source':46} {'Scope':7} {'Filled/Total':>18} {'%':>7}")
    print("-" * 128)
    results = []
    for owner, table, col, label, scope in FIELDS:
        dtype = col_type(cur, table, col)
        src = f"{table}.{col}"
        if dtype is None:
            print(f"{owner:13} {label:30} {src:46} {'—':7} {'(column not found)':>18}")
            continue
        pred = filled_pred(col, dtype)
        sql = f"SELECT COUNT(*) AS total, SUM(CASE WHEN {pred} THEN 1 ELSE 0 END) AS filled " \
              f"FROM dbo.[{table}] {scope_clause(table, scope)}"
        try:
            cur.execute(sql)
            total, filled = cur.fetchone()
            total = int(total or 0); filled = int(filled or 0)
            pct = (100.0 * filled / total) if total else 0.0
            sc = "active" if scope in ("active", "active_self") else "all"
            print(f"{owner:13} {label:30} {src:46} {sc:7} {f'{filled:,}/{total:,}':>18} {pct:6.1f}%")
            results.append((owner, label, src, sc, filled, total, pct))
        except Exception as e:
            print(f"{owner:13} {label:30} {src:46} ERROR {str(e)[:40]}")

    # sparsest first
    print("\n" + "=" * 60 + "\nSPARSEST FIELDS (population < 50%), worst first\n" + "=" * 60)
    for owner, label, src, sc, filled, total, pct in sorted(results, key=lambda x: x[6]):
        if pct < 50:
            print(f"  {pct:6.1f}%   {label:30} ({owner}, {sc})   {filled:,}/{total:,}")

    # active-project denominator, for context
    cur.execute(f"SELECT COUNT(*) FROM ({ACTIVE}) a")
    print(f"\n(active-project scope = {cur.fetchone()[0]} projects with a charge in the last 12 months)")
    eto.close()


if __name__ == "__main__":
    main()
