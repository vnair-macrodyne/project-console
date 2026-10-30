"""
console_diag_bom_composition.py -- measure BOM/product composition for the 224 classified
projects, to test whether category groups + modular templates can be derived bottom-up.
READ-ONLY. Nothing is written to ETO. (2026-10-30)

Answers:
  A. Coverage -- how many of the 224 classified projects have a BOM in vwEngBOM; the UOMType
     split (AS assembly / PC piece / SA standard-assembly); and how well the item Category
     (CategoryDescription) is populated. (If these are sparse, bottom-up clustering is weak.)
  B. Top item categories overall (by BOM node count).
  C. Standard-Assembly REUSE -- the SA parts ranked by how many distinct projects use them.
     These are the candidate shared "modules" for a modular architecture.
  D. Per project TYPE (from the Sextant classification, embedded below): the dominant item
     categories and the count of distinct standard assemblies -- a first "module signature".
  Also writes two CSVs next to the script for deeper clustering:
     bom_by_project_cat.csv   (ProjectID, Category, Nodes, DistinctItems)
     sa_reuse.csv             (SA_PartNumber, Description, nProjects, nOccurrences)

Run from the repo root:   python console_diag_bom_composition.py
Paste the printed summary; upload the two CSVs for the type-level clustering.
"""
import csv, sys
from collections import defaultdict


def eto_connect():
    try:
        from console_store import eto_connection
        return eto_connection()
    except Exception:
        import os, pyodbc
        from console_config import TENANT
        cs = (f"Driver={{ODBC Driver 17 for SQL Server}};Server={TENANT.eto_server};"
              f"Database={TENANT.eto_database};Trusted_Connection=yes;TrustServerCertificate=yes;")
        return pyodbc.connect(cs, timeout=60)


PROJ_CAT = {
    111163: 'Forging', 121432: 'Press', 141614: 'Metalforming', 141615: 'Compression Molding (SMC)',
    161665: 'Metalforming', 161672: 'Warranty Work', 161674: 'Mechanical Retrofits', 161679: 'Compression Molding (SMC)',
    161682: 'Press', 161683: 'Press', 161684: 'Press', 161689: 'Hot Stamping / Heated Platen',
    171726: 'Compression Molding (SMC)', 171731: 'Blanking Press', 171732: 'Blanking Press', 171738: 'Material Handling',
    171740: 'Press Lines / Cells', 171744: 'Press', 171745: 'Compression Molding (SMC)', 171747: 'Metalforming',
    171766: 'Press', 181772: 'Compression Molding (SMC)', 181773: 'Compression Molding (SMC)', 181775: 'Metalforming',
    181781: 'Material Handling', 181782: 'Hot Stamping / Heated Platen', 181784: 'Extrusion', 181785: 'Auxiliary Systems',
    181788: 'Hot Stamping / Heated Platen', 181789: 'Draw / Deep Draw', 181794: 'Press', 181795: 'Press',
    181797: 'Press', 181803: 'Mechanical Retrofits', 181810: 'Press', 181811: 'Prototype / Testing',
    181812: 'Assembly Press', 181814: 'Mechanical Retrofits', 181820: 'Mechanical Retrofits', 181821: 'Warranty Work',
    181843: 'Hot Stamping / Heated Platen', 181844: 'Auxiliary Systems', 181846: 'Press', 181853: 'Mechanical Retrofits',
    181866: 'Press', 181879: 'Mechanical Retrofits', 181881: 'Compression Molding (SMC)', 181884: 'Press',
    181906: 'Metalforming', 191918: 'Compression Molding (SMC)', 191920: 'Press', 191925: 'Draw / Deep Draw',
    191926: 'Compression Molding (SMC)', 191947: 'Hydroforming / SPF', 191955: 'Metalforming', 191956: 'Forging',
    191959: 'Mechanical Retrofits', 192007: 'Press Lines / Cells', 192009: 'Metalforming', 192012: 'Draw / Deep Draw',
    192014: 'Press Lines / Cells', 192020: 'Press', 192033: 'Draw / Deep Draw', 192038: 'Hydroforming / SPF',
    192051: 'Press', 192053: 'Mechanical Retrofits', 192057: 'Compression Molding (SMC)', 192085: 'Press',
    192094: 'Hydroforming / SPF', 192124: 'Compression Molding (SMC)', 192133: 'Mechanical Retrofits', 192137: 'Hydroforming / SPF',
    192142: 'Metalforming', 192143: 'Hot Stamping / Heated Platen', 192151: 'Mechanical Retrofits', 192159: 'Draw / Deep Draw',
    202170: 'Press', 202190: 'Mechanical Retrofits', 202191: 'Prototype / Testing', 202207: 'Press',
    202209: 'Mechanical Retrofits', 202213: 'Thermal Systems', 202215: 'Compression Molding (SMC)', 202216: 'Mechanical Retrofits',
    202228: 'Press Lines / Cells', 202234: 'Mechanical Retrofits', 202245: 'Mechanical Retrofits', 202251: 'Mechanical Retrofits',
    202295: 'Compression Molding (SMC)', 202325: 'Pulp Bailing Press', 202330: 'Compression Molding (SMC)', 202336: 'Compression Molding (SMC)',
    202337: 'Compression Molding (SMC)', 202342: 'Hydroforming / SPF', 202349: 'Mechanical Retrofits', 202351: 'Draw / Deep Draw',
    202360: 'Press', 202365: 'Press', 202369: 'Simulation & Process Dev', 202374: 'Compression Molding (SMC)',
    202375: 'Press', 202394: 'Metalforming', 202418: 'Specialty Presses', 202431: 'Metalforming',
    202434: 'Mechanical Retrofits', 202436: 'Hydroforming / SPF', 202445: 'Metalforming', 202449: 'Press Lines / Cells',
    202453: 'Press', 202454: 'Press', 202469: 'Specialty Presses', 202472: 'Metalforming',
    202480: 'Compression Molding (SMC)', 202482: 'Mechanical Retrofits', 202483: 'Non-Standard / Other', 202484: 'Compression Molding (SMC)',
    210019: 'Press', 210024: 'Specialty Presses', 210026: 'Mechanical Retrofits', 210031: 'Automation Systems',
    210061: 'Metalforming', 210065: 'Pulp Bailing Press', 210073: 'Compression Molding (SMC)', 210140: 'Extrusion',
    210155: 'Extrusion', 210169: 'Controls Retrofits', 210205: 'Press', 210206: 'Compression Molding (SMC)',
    210214: 'Compression Molding (SMC)', 210242: 'Mechanical Retrofits', 210275: 'Compression Molding (SMC)', 210286: 'Mechanical Retrofits',
    210292: 'Specialty Presses', 210307: 'Compression Molding (SMC)', 210338: 'Press', 210361: 'Compression Molding (SMC)',
    210375: 'Press', 210412: 'Press', 210428: 'Press', 210447: 'Automation Systems',
    219999: 'R&D / Internal Projects', 220006: 'Mechanical Retrofits', 220035: 'Compression Molding (SMC)', 220096: 'R&D / Internal Projects',
    220097: 'Compression Molding (SMC)', 220109: 'Pulp Bailing Press', 220203: 'Hot Stamping / Heated Platen', 220220: 'Mechanical Retrofits',
    220234: 'Compression Molding (SMC)', 220296: 'Non-Standard / Other', 220317: 'Mechanical Retrofits', 220324: 'Prototype / Testing',
    220352: 'Hydroforming / SPF', 220359: 'Forging', 220384: 'Mechanical Retrofits', 220389: 'Press',
    230006: 'Pulp Bailing Press', 230044: 'Hydroforming / SPF', 230049: 'Engineering Studies', 230070: 'Simulation & Process Dev',
    230080: 'Press', 230084: 'Prototype / Testing', 230092: 'Press Lines / Cells', 230093: 'Automation Systems',
    230105: 'Mechanical Retrofits', 230127: 'Extrusion', 230129: 'Extrusion', 230134: 'Forging',
    230149: 'Extrusion', 230151: 'Controls Retrofits', 230152: 'Hydroforming / SPF', 230187: 'Extrusion',
    230196: 'Hot Stamping / Heated Platen', 230204: 'Mechanical Retrofits', 230206: 'Mechanical Retrofits', 230219: 'Forging',
    240010: 'Prototype / Testing', 240021: 'Metalforming', 240033: 'Metalforming', 240040: 'Draw / Deep Draw',
    240043: 'Extrusion', 240044: 'Stretch Forming', 240051: 'Draw / Deep Draw', 240054: 'Press',
    240081: 'Prototype / Testing', 240088: 'Press Lines / Cells', 240115: 'Material Handling', 240141: 'Extrusion',
    240146: 'Hydroforming / SPF', 240148: 'Hydroforming / SPF', 240154: 'Hot Stamping / Heated Platen', 240160: 'Press',
    240166: 'Hot Stamping / Heated Platen', 240218: 'Specialty Presses', 240222: 'R&D / Internal Projects', 240232: 'Hydroforming / SPF',
    240244: 'Compression Molding (SMC)', 250005: 'Forging', 250043: 'Non-Standard / Other', 250099: 'Hydroforming / SPF',
    250130: 'Forging', 250138: 'Press', 250148: 'Press', 250161: 'Draw / Deep Draw',
    250163: 'Non-Standard / Other', 250164: 'Auxiliary Systems', 250181: 'Hydroforming / SPF', 250209: 'Simulation & Process Dev',
    250250: 'Compression Molding (SMC)', 250251: 'Non-Standard / Other', 250259: 'Press Lines / Cells', 250269: 'Non-Standard / Other',
    250284: 'Press', 250309: 'Non-Standard / Other', 250340: 'Stretch Forming', 260027: 'Simulation & Process Dev',
    260054: 'Hot Stamping / Heated Platen', 260078: 'Non-Standard / Other', 260079: 'Mechanical Retrofits', 260087: 'Simulation & Process Dev',
    260115: 'Engineering Studies', 260118: 'Specialty Presses', 260168: 'Compression Molding (SMC)', 260178: 'Press',
}

GROUP_OF = {}  # filled after PROJ_CAT via the taxonomy below
TAXO = {
    "Core Press Types": ["Press","Compression Molding (SMC)","Metalforming","Hydroforming / SPF",
        "Hot Stamping / Heated Platen","Extrusion","Draw / Deep Draw","Forging","Specialty Presses",
        "Pulp Bailing Press","Blanking Press","Stretch Forming","Assembly Press"],
    "Retrofit / Upgrades": ["Mechanical Retrofits","Controls Retrofits"],
    "Systems": ["Press Lines / Cells","Automation Systems"],
    "Subsystems": ["Material Handling","Auxiliary Systems","Thermal Systems"],
    "Engineering": ["Prototype / Testing","Simulation & Process Dev","R&D / Internal Projects","Engineering Studies"],
    "Aftermarket": ["Warranty Work"],
    "Misc": ["Non-Standard / Other"],
}
for g, cs in TAXO.items():
    for c in cs:
        GROUP_OF[c] = g


def q(cur, sql, args=None):
    cur.execute(sql, args) if args else cur.execute(sql)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def main():
    ids = sorted(PROJ_CAT)
    idcsv = ",".join(str(i) for i in ids)
    eto = eto_connect(); cur = eto.cursor()

    # pick a BOM source view/table + its column names defensively
    print("=" * 78); print("BOM source + columns"); print("=" * 78)
    SRC = None
    for cand in ("vwEngBOM", "vwEngProductStructure"):
        try:
            cols, _ = q(cur, f"SELECT TOP 1 * FROM {cand}")
            print(f"  {cand} columns: {cols}")
            SRC = cand; SRCCOLS = cols; break
        except Exception as e:
            print(f"  {cand}: ERROR {e}")
    if not SRC:
        print("No BOM view available; aborting."); return
    has = lambda c: c in SRCCOLS
    catcol = "CategoryDescription" if has("CategoryDescription") else None
    uom = "UOMType" if has("UOMType") else None
    pn = "ItemCompanyID" if has("ItemCompanyID") else None
    desc = "ItemDescription" if has("ItemDescription") else None
    print(f"  using: category={catcol} uom={uom} partno={pn} desc={desc}")

    # ---------- A. coverage ----------
    print("\n" + "=" * 78); print("A. coverage over the 224 classified projects"); print("=" * 78)
    cols, rows = q(cur, f"SELECT COUNT(DISTINCT ProjectID), COUNT(*) FROM {SRC} WHERE ProjectID IN ({idcsv})")
    nproj, nnodes = rows[0]
    print(f"  projects with a BOM: {nproj} / {len(ids)}   total BOM nodes: {nnodes}")
    if uom:
        _, r = q(cur, f"SELECT {uom}, COUNT(*) FROM {SRC} WHERE ProjectID IN ({idcsv}) GROUP BY {uom} ORDER BY COUNT(*) DESC")
        print("  UOMType split:", ", ".join(f"{u}={n}" for u, n in r))
    if catcol:
        _, r = q(cur, f"SELECT SUM(CASE WHEN {catcol} IS NULL OR {catcol}='' THEN 0 ELSE 1 END), COUNT(*) "
                      f"FROM {SRC} WHERE ProjectID IN ({idcsv})")
        filled, tot = r[0]
        print(f"  item Category populated on {filled}/{tot} nodes ({(100.0*filled/tot if tot else 0):.0f}%)")

    # ---------- B. top item categories overall ----------
    by_proj_cat = defaultdict(lambda: [0, 0])   # (pid,cat) -> [nodes, items]
    if catcol:
        print("\n" + "=" * 78); print("B. top item categories overall (by node count)"); print("=" * 78)
        _, r = q(cur, f"SELECT ProjectID, COALESCE(NULLIF({catcol},''),'(none)') AS Cat, COUNT(*) AS Nodes, "
                      f"COUNT(DISTINCT ItemID) AS Items FROM {SRC} WHERE ProjectID IN ({idcsv}) "
                      f"GROUP BY ProjectID, COALESCE(NULLIF({catcol},''),'(none)')")
        cat_tot = defaultdict(int)
        for pid, cat, nodes, itemz in r:
            by_proj_cat[(int(pid), cat)] = [int(nodes), int(itemz)]
            cat_tot[cat] += int(nodes)
        for cat, n in sorted(cat_tot.items(), key=lambda kv: -kv[1])[:30]:
            print(f"   {n:8d}  {cat}")

    # ---------- C. standard-assembly reuse ----------
    sa_rows = []
    if uom and pn:
        print("\n" + "=" * 78); print("C. standard-assembly (UOMType='SA') reuse -- candidate modules"); print("=" * 78)
        _, r = q(cur, f"SELECT {pn} AS PN, MAX({desc if desc else pn}) AS Descr, "
                      f"COUNT(DISTINCT ProjectID) AS nProj, COUNT(*) AS nOcc FROM {SRC} "
                      f"WHERE UOMType='SA' AND ProjectID IN ({idcsv}) AND {pn} IS NOT NULL "
                      f"GROUP BY {pn} ORDER BY COUNT(DISTINCT ProjectID) DESC, COUNT(*) DESC")
        sa_rows = [(pnx, (d or ""), int(np), int(no)) for pnx, d, np, no in r]
        print(f"  distinct SA parts used across the set: {len(sa_rows)}")
        print("  top SAs by # projects using them:")
        for pnx, d, np, no in sa_rows[:40]:
            print(f"   {np:3d} proj  {no:5d} occ   {pnx:<18} {d[:60]}")

    # ---------- D. per project-type module signature ----------
    print("\n" + "=" * 78); print("D. per project TYPE: dominant item categories + # distinct SAs"); print("=" * 78)
    # nodes by (type, itemcat)
    type_cat = defaultdict(lambda: defaultdict(int))
    type_nproj = defaultdict(set)
    for (pid, cat), (nodes, itemz) in by_proj_cat.items():
        t = PROJ_CAT.get(pid)
        if t is None:
            continue
        type_cat[t][cat] += nodes
        type_nproj[t].add(pid)
    # distinct SA count per type needs a per-(type) query; approximate from CSV-level data:
    type_sa = defaultdict(set)
    if uom and pn:
        _, r = q(cur, f"SELECT ProjectID, {pn} FROM {SRC} WHERE UOMType='SA' AND ProjectID IN ({idcsv}) AND {pn} IS NOT NULL")
        for pid, pnx in r:
            t = PROJ_CAT.get(int(pid))
            if t:
                type_sa[t].add(pnx)
    order = sorted(type_cat, key=lambda t: -sum(type_cat[t].values()))
    for t in order:
        tot = sum(type_cat[t].values())
        top = sorted(type_cat[t].items(), key=lambda kv: -kv[1])[:5]
        topstr = "; ".join(f"{c} {int(100.0*n/tot) if tot else 0}%" for c, n in top)
        print(f"  [{GROUP_OF.get(t,'?')}] {t}: {len(type_nproj[t])} proj w/BOM, "
              f"{len(type_sa.get(t,()))} distinct SAs")
        print(f"       top item cats: {topstr}")

    # ---------- CSVs ----------
    with open("bom_by_project_cat.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["ProjectID", "ProjectType", "ItemCategory", "Nodes", "DistinctItems"])
        for (pid, cat), (nodes, itemz) in sorted(by_proj_cat.items()):
            w.writerow([pid, PROJ_CAT.get(pid, ""), cat, nodes, itemz])
    with open("sa_reuse.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["SA_PartNumber", "Description", "nProjects", "nOccurrences"])
        for pnx, d, np, no in sa_rows:
            w.writerow([pnx, d, np, no])
    print("\nWROTE bom_by_project_cat.csv and sa_reuse.csv -- upload both for the clustering step.")
    eto.close(); print("\n--- done ---")


if __name__ == "__main__":
    main()
