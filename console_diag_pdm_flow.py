"""
console_diag_pdm_flow.py — PDM vault engineering-flow analysis for EVERY project. (2026-11-20)
READ-ONLY: SELECTs only. Refreshes the 3 Nov SSMS analysis (SQL_Scrub_5) across the whole vault.

Connects like console_diag_pdm_vault.py (same env vars):
    $env:VAULT_SERVER  = 'MACRO-SOLID-SVR\\SOLIDWORKS'
    $env:VAULT_DB      = 'Macrodyne'
    $env:VAULT_TRUSTED = '1'            # or VAULT_USER / VAULT_PWD

Run from the repo root:
    python console_diag_pdm_flow.py
Writes beside it:
    diag_pdm_flow_<date>.txt            the report below
    diag_pdm_flow_projects_<date>.csv   one row per project (open in Excel)

How a file is assigned to a project (first that applies, counted in the report):
    1. file name starts with a 6-digit project number   (250005-20A2.3.1.0-01.SLDPRT)
    2. its data-card Number starts with one             (Number = 250005-…)
    3. it sits in a vault folder named with one         (\\1. Mechanical\\2025\\250005\\…)
Files that match none are counted as "unassigned" (library parts such as CC - ME00xxxxx).

Sections:
  A. vault totals and how files were assigned to projects
  B. workflow transitions actually used (state from -> to, count, enabled), with which of them
     count as a review kick-back
  C. per-project table (also the CSV): files by type, carded parts, folders, engineers, versions,
     first/last activity, parts reaching Drawing Approved / ERP Data Entry / In Production,
     kick-backs, median days from first touch to Drawing Approved
  D. vault activity by month: versions saved, active projects, active engineers (adoption trend)
  E. engineers: versions saved and projects touched
"""
import csv
import datetime as _dt
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

from console_diag_pdm_vault import vault_connection

PROJ_PREFIX = re.compile(r"^(\d{6})(?!\d)")
PROJ_FOLDER = re.compile(r"\\(\d{6})(?=\\|$)")
REV_SUFFIX = re.compile(r"-\d{2}$")

MILESTONES = ["Drawing Approved", "ERP Data Entry", "In Production"]
# A kick-back = a part sent from a review/approval state back to a working state.
REVIEW_STATES = {"waiting for peer approval", "design review", "final drawing approval",
                 "design approved"}
WORK_STATES = {"initiated", "general concept design", "design in progress", "making drawings"}


class Tee:
    def __init__(self, path):
        self.f = open(path, "w", encoding="utf-8")

    def write(self, s):
        sys.__stdout__.write(s); self.f.write(s)

    def flush(self):
        sys.__stdout__.flush(); self.f.flush()


def rule(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def rows(cur, sql):
    cur.execute(sql)
    return cur.fetchall()


def day(v):
    if v is None:
        return None
    if isinstance(v, _dt.datetime):
        return v.date()
    return v


def ext_of(name):
    i = name.rfind(".")
    return name[i:].upper() if i >= 0 else ""


def load(cur):
    """Pull the small vault tables into memory; joins are done in Python."""
    data = {}
    data["docs"] = rows(cur, "SELECT DocumentID, Filename FROM dbo.Documents WHERE Deleted = 0")
    data["status"] = dict(rows(cur, "SELECT StatusID, Name FROM dbo.Status"))
    data["users"] = dict(rows(cur, "SELECT UserID, FullName FROM dbo.Users"))
    data["transitions"] = rows(cur, "SELECT TransitionID, Name, Source, Destination, Enabled "
                                    "FROM dbo.Transitions")
    data["number"] = rows(cur, """
        SELECT vv.DocumentID, vv.RevisionNo, vv.ValueText
        FROM dbo.VariableValue vv JOIN dbo.Variable v ON v.VariableID = vv.VariableID
        WHERE v.VariableName = 'Number' AND vv.ValueText IS NOT NULL AND vv.ValueText <> ''""")
    data["folders"] = rows(cur, """
        SELECT dip.DocumentID, p.Path
        FROM dbo.DocumentsInProjects dip JOIN dbo.Projects p ON p.ProjectID = dip.ProjectID""")
    data["revisions"] = rows(cur, "SELECT DocumentID, RevNr, [Date], UserID FROM dbo.Revisions")
    data["history"] = rows(cur, "SELECT DocumentID, TransitionID, [Date], UserID "
                                "FROM dbo.TransitionHistory")
    return data


def assign_projects(data):
    """{DocumentID: (project, how)} using file name, then card Number, then folder."""
    latest_number = {}
    for doc, rev, val in data["number"]:
        cur = latest_number.get(doc)
        if cur is None or (rev or 0) >= cur[0]:
            latest_number[doc] = (rev or 0, val.strip())
    folder_proj = defaultdict(set)
    folder_count = defaultdict(set)
    for doc, path in data["folders"]:
        m = PROJ_FOLDER.search(path or "")
        if m:
            folder_proj[doc].add(m.group(1))
            folder_count[m.group(1)].add(path)
    assigned = {}
    for doc, name in data["docs"]:
        m = PROJ_PREFIX.match(name or "")
        if m:
            assigned[doc] = (m.group(1), "file name")
            continue
        num = latest_number.get(doc)
        if num is not None:
            m = PROJ_PREFIX.match(num[1])
            if m:
                assigned[doc] = (m.group(1), "card Number")
                continue
        if folder_proj[doc]:
            assigned[doc] = (min(folder_proj[doc]), "folder")
    return assigned, latest_number, folder_count


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    stamp = f"{_dt.date.today():%Y%m%d}"
    out = os.path.join(here, f"diag_pdm_flow_{stamp}.txt")
    out_csv = os.path.join(here, f"diag_pdm_flow_projects_{stamp}.csv")
    sys.stdout = Tee(out)
    print(f"console_diag_pdm_flow — {_dt.datetime.now():%Y-%m-%d %H:%M}")
    conn = vault_connection()
    try:
        data = load(conn.cursor())
    finally:
        conn.close()

    status, users = data["status"], data["users"]
    names = dict(data["docs"])
    assigned, latest_number, folder_count = assign_projects(data)

    rule("A. Vault totals and project assignment")
    print(f"   files (not deleted): {len(names)}")
    print(f"   versions: {len(data['revisions'])}   workflow transitions: {len(data['history'])}")
    how = Counter(h for _, h in assigned.values())
    for k in ("file name", "card Number", "folder"):
        print(f"   assigned by {k:12}: {how[k]}")
    print(f"   unassigned (library / non-project): {len(names) - len(assigned)}")
    print(f"   projects found: {len({p for p, _ in assigned.values()})}")

    rule("B. Workflow transitions actually used")
    trans = {}
    for tid, tname, src, dst, enabled in data["transitions"]:
        trans[tid] = (tname, status.get(src, f"#{src}"), status.get(dst, f"#{dst}"), enabled)
    used = Counter(tid for _, tid, _, _ in data["history"])
    print(f"   {'count':>6}  {'enabled':7}  {'kick-back':9}  from -> to   [transition name]")
    for tid, n in used.most_common():
        tname, src, dst, enabled = trans.get(tid, ("?", "?", "?", None))
        kick = (src or "").lower() in REVIEW_STATES and (dst or "").lower() in WORK_STATES
        print(f"   {n:6}  {str(enabled):7}  {'yes' if kick else '':9}  {src} -> {dst}   [{tname}]")

    # ---- per project ------------------------------------------------------------------------
    proj_docs = defaultdict(set)
    for doc, (proj, _) in assigned.items():
        proj_docs[proj].add(doc)
    revs_by_doc = defaultdict(list)
    for doc, rev, when, uid in data["revisions"]:
        revs_by_doc[doc].append((day(when), uid))
    hist_by_doc = defaultdict(list)
    for doc, tid, when, uid in data["history"]:
        hist_by_doc[doc].append((day(when), tid))

    table = []
    for proj in sorted(proj_docs):
        docs = proj_docs[proj]
        exts = Counter(ext_of(names[d]) for d in docs)
        parts = {REV_SUFFIX.sub("", latest_number[d][1]) for d in docs if d in latest_number}
        dates = [w for d in docs for w, _ in revs_by_doc[d] if w is not None]
        engineers = {uid for d in docs for _, uid in revs_by_doc[d]}
        reached = {m: {} for m in MILESTONES}
        kicks = 0
        for d in docs:
            for when, tid in hist_by_doc[d]:
                _, src, dst, _ = trans.get(tid, ("?", "?", "?", None))
                if dst in reached and when is not None:
                    prev = reached[dst].get(d)
                    reached[dst][d] = when if prev is None else min(prev, when)
                if (src or "").lower() in REVIEW_STATES and (dst or "").lower() in WORK_STATES:
                    kicks += 1
        to_approval = []
        for d, when in reached["Drawing Approved"].items():
            touches = [w for w, _ in revs_by_doc[d] if w is not None]
            if touches:
                to_approval.append((when - min(touches)).days)
        first_of = {m: (min(v.values()) if v else None) for m, v in reached.items()}
        table.append({
            "Project": proj,
            "Files": len(docs),
            "Parts (.SLDPRT)": exts[".SLDPRT"],
            "Assemblies (.SLDASM)": exts[".SLDASM"],
            "Drawings (.SLDDRW)": exts[".SLDDRW"],
            "Carded parts": len(parts),
            "Folders": len(folder_count.get(proj, ())),
            "Engineers": len(engineers),
            "Versions": sum(len(revs_by_doc[d]) for d in docs),
            "First touch": min(dates) if dates else None,
            "Last touch": max(dates) if dates else None,
            "Drawing Approved (files)": len(reached["Drawing Approved"]),
            "First Drawing Approved": first_of["Drawing Approved"],
            "ERP Data Entry (files)": len(reached["ERP Data Entry"]),
            "First ERP Data Entry": first_of["ERP Data Entry"],
            "In Production (files)": len(reached["In Production"]),
            "Kick-backs": kicks,
            "Median days first touch -> Drawing Approved":
                statistics.median(to_approval) if to_approval else None,
        })

    rule("C. Per project (largest first; full list in the CSV)")
    cols = list(table[0].keys()) if table else []
    short = ["Project", "Files", "Carded parts", "Folders", "Engineers", "Versions", "First touch",
             "Last touch", "Drawing Approved (files)", "ERP Data Entry (files)", "Kick-backs",
             "Median days first touch -> Drawing Approved"]
    hdr = ["Project", "Files", "Carded", "Folders", "Engs", "Versions", "First", "Last",
           "DrwAppr", "ERPEntry", "Kicks", "MedDays"]
    print("   " + " | ".join(f"{h:>10}" for h in hdr))
    for r in sorted(table, key=lambda x: -x["Files"]):
        print("   " + " | ".join(f"{str(r[c]) if r[c] is not None else '':>10}" for c in short))
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in sorted(table, key=lambda x: x["Project"]):
            w.writerow(r)

    rule("D. Vault activity by month")
    by_month = defaultdict(lambda: [0, set(), set()])
    for doc, rev, when, uid in data["revisions"]:
        if when is None:
            continue
        key = f"{when:%Y-%m}"
        by_month[key][0] += 1
        by_month[key][2].add(uid)
        if doc in assigned:
            by_month[key][1].add(assigned[doc][0])
    print("   month   | versions | projects | engineers")
    for key in sorted(by_month):
        v, p, e = by_month[key]
        print(f"   {key} | {v:8} | {len(p):8} | {len(e):9}")

    rule("E. Engineers")
    eng = defaultdict(lambda: [0, set(), None, None])
    for doc, rev, when, uid in data["revisions"]:
        e = eng[uid]
        e[0] += 1
        if doc in assigned:
            e[1].add(assigned[doc][0])
        w = day(when)
        if w is not None:
            e[2] = w if e[2] is None else min(e[2], w)
            e[3] = w if e[3] is None else max(e[3], w)
    print("   engineer                       | versions | projects | first      | last")
    for uid, (v, p, first, last) in sorted(eng.items(), key=lambda x: -x[1][0]):
        print(f"   {str(users.get(uid, uid))[:30]:30} | {v:8} | {len(p):8} | {first} | {last}")

    print(f"\nDone. Report: {out}\n      Projects CSV: {out_csv}\n[read-only — no writes issued]")


if __name__ == "__main__":
    main()
