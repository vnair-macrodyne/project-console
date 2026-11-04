"""console_diag_pdm_vault.py - READ-ONLY discovery probe for the SolidWorks PDM (EPDM) vault DB.

Peter's "PDM sleuthing" work: before we build anything, confirm what the vault's SQL database
actually holds and nail the ETO<->PDM join. NO GUESSES - this script DISCOVERS the schema from
INFORMATION_SCHEMA first and prints it, then runs best-effort targeted profiles that degrade
gracefully if a table isn't named what we expect. It only ever SELECTs - no writes, no DDL.

It connects to the VAULT database independently of Sextant's ETO/Console config, via env vars:

    set VAULT_SERVER=YOURSQLHOST\\INSTANCE        (e.g. the PDM archive/SQL server)
    set VAULT_DB=YourVaultName                     (the vault database name)
    # SQL auth:
    set VAULT_USER=readonly_login
    set VAULT_PWD=********
    # ...or Windows auth instead of USER/PWD:
    set VAULT_TRUSTED=1
    # optional:
    set VAULT_DRIVER=ODBC Driver 17 for SQL Server   (default)
    set PILOT_PROJECT=250005                          (ETO project number to trace; default 250005)

Run from the repo root with the same Python as the other console_diag_* scripts:
    python console_diag_pdm_vault.py
or pass the pilot project as an argument:
    python console_diag_pdm_vault.py 250005

What it reports:
  A. Table inventory (name + row count), with likely-EPDM core tables flagged.
  B. The Documents table (file rows): columns + samples + count  -> is the filename the part number?
  C. Data-card Variables: distinct variable names  -> is there a Project No / Part No / Drawing No card
     field that is the ETO join key?
  D. Workflow Status / Workflow: the state names (WIP / In Work / Under Review / Released / ...).
  E. Users: count + sample (the "unique engineers" universe).
  F. History / transition tables: any table with a datetime + a user/document column = the touchpoint
     log; prints columns, row count and min/max date (this is where "when work starts", "period
     between events" and the revision trail live).
  G. Pilot join probe: how the ETO project number (default 250005) shows up in the vault - in file
     names, in folder paths, and in data-card variable values. This is the crux of Peter's
     "find the part in PDM and trace it back to the project".
"""
import os
import sys


# ---- connection (independent of Sextant TENANT config) ----------------------------------------
def vault_connection():
    import pyodbc
    server = os.environ.get("VAULT_SERVER")
    database = os.environ.get("VAULT_DB")
    driver = os.environ.get("VAULT_DRIVER", "ODBC Driver 17 for SQL Server")
    if not server or not database:
        sys.exit("Set VAULT_SERVER and VAULT_DB (and VAULT_USER/VAULT_PWD or VAULT_TRUSTED). "
                 "See the docstring at the top of this file.")
    cs = f"Driver={{{driver}}};Server={server};Database={database};"
    if os.environ.get("VAULT_TRUSTED"):
        cs += "Trusted_Connection=yes;"
    else:
        u, p = os.environ.get("VAULT_USER"), os.environ.get("VAULT_PWD")
        if not (u and p):
            sys.exit("Set VAULT_USER/VAULT_PWD for SQL auth, or VAULT_TRUSTED=1 for Windows auth.")
        cs += f"UID={u};PWD={p};"
    # ApplicationIntent=ReadOnly is harmless if the server isn't an AG; keeps intent explicit.
    cs += "ApplicationIntent=ReadOnly;"
    print(f"[connect] {server} / {database}  (read-only intent)")
    return pyodbc.connect(cs, timeout=30)


def run(cur, sql, params=None):
    cur.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def hr(title):
    print("\n" + "=" * 78 + f"\n{title}\n" + "=" * 78)


def d(v):
    if v is None:
        return ""
    try:
        return v.isoformat()[:19]
    except Exception:
        return str(v)[:19]


# ---- schema model (the ground truth; everything else is best-effort) ---------------------------
def load_schema(cur):
    """{table_lower: {'name': realname, 'cols': [realcol, ...], 'colset': {lower, ...}}}"""
    _, rows = run(cur, """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
        ORDER BY TABLE_NAME, ORDINAL_POSITION""")
    tbl = {}
    for t, c, dt in rows:
        e = tbl.setdefault(t.lower(), {"name": t, "cols": [], "colset": set(), "types": {}})
        e["cols"].append(c)
        e["colset"].add(c.lower())
        e["types"][c.lower()] = (dt or "").lower()
    return tbl


def rowcounts(cur):
    try:
        _, rows = run(cur, """
            SELECT t.name, SUM(p.row_count) AS rows
            FROM sys.tables t
            JOIN sys.dm_db_partition_stats p
              ON p.object_id = t.object_id AND p.index_id IN (0, 1)
            GROUP BY t.name""")
        return {t.lower(): int(r or 0) for t, r in rows}
    except Exception as e:
        print("  (rowcount fast-path failed, continuing without counts:", e, ")")
        return {}


def find_tables(schema, need_cols):
    """tables whose column set contains ALL of need_cols (lowercased substrings matched exactly)."""
    out = []
    for low, e in schema.items():
        if all(any(nc == col for col in e["colset"]) for nc in need_cols):
            out.append(e["name"])
    return out


def pick(schema, *candidates):
    """first existing table (case-insensitive) from candidate names."""
    for name in candidates:
        if name.lower() in schema:
            return schema[name.lower()]["name"]
    return None


def samples(cur, table, cols, n=8):
    collist = ", ".join(f"[{c}]" for c in cols)
    try:
        c, rows = run(cur, f"SELECT TOP {n} {collist} FROM [{table}]")
        print("   cols:", ", ".join(c))
        for r in rows:
            print("   ", " | ".join(("" if v is None else str(v))[:34] for v in r))
    except Exception as e:
        print("   (sample failed:", e, ")")


# ---- sections ----------------------------------------------------------------------------------
def section_inventory(schema, counts):
    hr("A. TABLE INVENTORY (row counts; * = likely EPDM core)")
    CORE = ("documents", "documentsinprojects", "projects", "status", "workflow",
            "workflowtransitions", "transitions", "variable", "variablevalue",
            "variablevaluecache", "users", "groups", "revisions", "objectproperties",
            "history", "objecthistory", "documentactionlog", "transitionhistory",
            "documentconfiguration", "versionrefs", "logfiles")
    for low in sorted(schema, key=lambda k: -counts.get(k, 0)):
        flag = " *" if low in CORE else ""
        print(f"  {schema[low]['name']:<42} {counts.get(low, '?'):>12}{flag}")
    print(f"\n  total tables: {len(schema)}")


def section_documents(cur, schema):
    hr("B. DOCUMENTS (file rows) - is the filename the part number?")
    t = pick(schema, "Documents")
    if not t:
        # discover: a table with a filename-ish column
        cand = [e["name"] for e in schema.values()
                if any("filename" == c or "file_name" == c for c in e["colset"])
                or ("filename" in " ".join(e["colset"]))]
        print("  no 'Documents' table; filename-bearing candidates:", cand or "(none)")
        t = cand[0] if cand else None
    if not t:
        return
    print(f"  table: {t}")
    cols = [c for c in schema[t.lower()]["cols"]
            if c.lower() in ("documentid", "filename", "latestrevisionno", "currentstatusid",
                             "latestversion", "deleted", "documenttype")]
    samples(cur, t, cols or schema[t.lower()]["cols"][:6])


def section_variables(cur, schema):
    hr("C. DATA-CARD VARIABLES - is there a Project No / Part No / Drawing No field (the ETO key)?")
    var = pick(schema, "Variable", "Variables")
    if var:
        try:
            _, rows = run(cur, f"SELECT [VariableID], [VariableName] FROM [{var}] ORDER BY [VariableName]")
            print(f"  {var}: {len(rows)} variables")
            for vid, vname in rows:
                print(f"    {vid:>5}  {vname}")
        except Exception as e:
            print("  (variable list failed:", e, "); columns =", schema[var.lower()]["cols"])
    else:
        print("  no Variable table found; card-variable candidates:",
              find_tables(schema, ["variableid"]) or "(none)")


def section_workflow(cur, schema):
    hr("D. WORKFLOW STATES (WIP / review / released / ...)")
    st = pick(schema, "Status")
    if st:
        samples(cur, st, schema[st.lower()]["cols"], n=50)
    wf = pick(schema, "Workflow", "Workflows")
    if wf:
        print("  workflows:")
        samples(cur, wf, schema[wf.lower()]["cols"], n=20)


def section_users(cur, schema):
    hr("E. USERS (the 'unique engineers' universe)")
    u = pick(schema, "Users", "User")
    if u:
        cols = [c for c in schema[u.lower()]["cols"]
                if c.lower() in ("userid", "username", "name", "fullname", "deleted")]
        samples(cur, u, cols or schema[u.lower()]["cols"][:5], n=12)
        try:
            _, r = run(cur, f"SELECT COUNT(*) FROM [{u}]")
            print("   total users:", r[0][0])
        except Exception:
            pass


def section_history(cur, schema, counts):
    hr("F. HISTORY / TRANSITION tables (touchpoints, gaps, revision trail)")
    DATE_HINTS = ("date", "time", "when", "stamp")
    ID_HINTS = ("documentid", "userid", "objectid")
    found = []
    for low, e in schema.items():
        has_date = any(any(h in c for h in DATE_HINTS) for c in e["colset"])
        has_id = any(c in ID_HINTS for c in e["colset"])
        datecols = [c for c in e["cols"] if any(h in c.lower() for h in DATE_HINTS)
                    and schema[low]["types"].get(c.lower(), "") in
                    ("datetime", "datetime2", "smalldatetime", "date")]
        if has_date and has_id and datecols:
            found.append((low, e["name"], datecols))
    if not found:
        print("  no obvious history table (date + id). Tables with a datetime column:")
        for low, e in schema.items():
            dc = [c for c in e["cols"] if schema[low]["types"].get(c.lower(), "").startswith("datetime")]
            if dc:
                print(f"    {e['name']}: {', '.join(dc)}")
        return
    for low, name, datecols in sorted(found, key=lambda x: -counts.get(x[0], 0)):
        print(f"\n  {name}  (rows ~{counts.get(low, '?')})")
        print("    cols:", ", ".join(schema[low]["cols"]))
        dc = datecols[0]
        try:
            _, r = run(cur, f"SELECT MIN([{dc}]), MAX([{dc}]) FROM [{name}]")
            print(f"    {dc} range: {d(r[0][0])}  ->  {d(r[0][1])}")
        except Exception as e:
            print("    (date range failed:", e, ")")


def section_pilot(cur, schema, pilot):
    hr(f"G. PILOT JOIN - how ETO project {pilot} shows up in the vault")
    like = f"%{pilot}%"
    # 1) filenames
    docs = pick(schema, "Documents")
    if docs and "filename" in schema[docs.lower()]["colset"]:
        try:
            _, r = run(cur, f"SELECT COUNT(*) FROM [{docs}] WHERE [Filename] LIKE ?", [like])
            print(f"  files with '{pilot}' in the name: {r[0][0]}")
            c, rows = run(cur, f"SELECT TOP 15 [Filename] FROM [{docs}] WHERE [Filename] LIKE ?", [like])
            for row in rows:
                print("     ", row[0])
        except Exception as e:
            print("  (filename search failed:", e, ")")
    # 2) folder paths
    proj = pick(schema, "Projects", "Project")
    if proj:
        pathcol = next((c for c in schema[proj.lower()]["cols"] if c.lower() in ("path", "name")), None)
        if pathcol:
            try:
                c, rows = run(cur, f"SELECT TOP 15 [{pathcol}] FROM [{proj}] WHERE [{pathcol}] LIKE ?", [like])
                print(f"\n  vault folders ({proj}.{pathcol}) containing '{pilot}': {len(rows)} shown")
                for row in rows:
                    print("     ", row[0])
            except Exception as e:
                print("  (folder search failed:", e, ")")
    # 3) data-card variable values carrying the project number
    vv = pick(schema, "VariableValue", "VariableValues")
    var = pick(schema, "Variable", "Variables")
    if vv:
        valcol = next((c for c in schema[vv.lower()]["cols"]
                       if c.lower() in ("valuetext", "value", "textvalue")), None)
        if valcol and var:
            try:
                sql = (f"SELECT TOP 30 v.[VariableName], vv.[{valcol}], COUNT(*) AS n "
                       f"FROM [{vv}] vv JOIN [{var}] v ON v.[VariableID] = vv.[VariableID] "
                       f"WHERE vv.[{valcol}] LIKE ? "
                       f"GROUP BY v.[VariableName], vv.[{valcol}] ORDER BY n DESC")
                c, rows = run(cur, sql, [like])
                print(f"\n  card variables whose VALUE contains '{pilot}' (= candidate join field):")
                for vn, val, n in rows:
                    print(f"     {vn:<24} = {str(val)[:30]:<30}  x{n}")
            except Exception as e:
                print("  (variable-value search failed:", e, ")")


def main():
    pilot = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PILOT_PROJECT", "250005")
    conn = vault_connection()
    try:
        cur = conn.cursor()
        schema = load_schema(cur)
        counts = rowcounts(cur)
        section_inventory(schema, counts)
        section_documents(cur, schema)
        section_variables(cur, schema)
        section_workflow(cur, schema)
        section_users(cur, schema)
        section_history(cur, schema, counts)
        section_pilot(cur, schema, pilot)
        print("\n[done] read-only probe complete - no writes were issued.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
