"""
EtoBudgetDAO — the project BUDGET sourced from ETO (the authoritative estimate),
replacing the manual Console store as the dashboard's budget denominator.

Owner decision 2026-07-27: budgets come from ETO.

SOURCING (finalised 2026-07-27 after the breadth check on 181 projects):
  * The 3-bucket estimate (Admin / Eng / Mfg hours) and material $ come from
    vwProjectActualsVSEstimates, ETO's authoritative rolled-up estimate — EXCEPT where a
    bucket there is 0/empty (a handful of projects), in which case we fall back to the
    tblSpecHours line-detail for that bucket so a missing rolled-up value never zeroes a
    real budget. (Verified: with straight view-anchoring all 181 reconcile; the fallback
    only changes the ~3 projects whose estimate view is empty but whose specs carry hours.)
  * tblSpecHours (grouped by HourType -> discipline, console.domain.hourtype_map) supplies
    (a) the fallback bucket totals and (b) the proportions that split the Eng bucket into
    Mechanical / Electrical / Hydraulic. Where a project has Eng hours but no Eng
    line-detail, the whole Eng total defaults to Mechanical.

  Result: PM = Admin, Manufacturing = Mfg, Mech+Elec+Hyd = Eng — reconciles by construction.

Schedule (ship dates, % done) is NOT in ETO — it stays the manual overlay, so those
Budget fields are left None; the dashboard reads them from the overlay as before.

Interface parity: get_current_many(project_ids) -> {pid: Budget}, same shape as
console.domain.budget.BudgetDAO, so ProjectFinancialsService is unchanged. Read-only ETO.
"""
from console.domain.budget import Budget
from console.infra.logging_config import get_logger

log = get_logger(__name__)

_ENG = ("Mechanical Engineering", "Hydraulic Engineering", "Electrical Engineering")


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


class EtoBudgetDAO:
    def __init__(self, eto_conn, hourtype_map: dict):
        """hourtype_map: {HourType(int): discipline} — the full map (PM/Mfg/Eng buckets)."""
        self._eto = eto_conn
        self._map = hourtype_map or {}

    def get_current_many(self, project_ids) -> dict:
        ids = [int(p) for p in (project_ids or [])]
        if not ids:
            return {}
        idlist = ",".join(str(p) for p in ids)
        cur = self._eto.cursor()

        # 1) authoritative rolled-up estimate + material $
        view = {}
        cur.execute(f"SELECT ProjectID, ISNULL(EstAdminHours,0), ISNULL(EstEngHours,0), "
                    f"ISNULL(EstMfgHours,0), EstTotalMaterials "
                    f"FROM dbo.vwProjectActualsVSEstimates WHERE ProjectID IN ({idlist})")
        for pid, a, e, m, matv in cur.fetchall():
            view[int(pid)] = (float(a or 0), float(e or 0), float(m or 0), _f(matv))

        # 2) tblSpecHours line-detail, mapped to buckets (fallback totals + Eng split)
        det = {}   # pid -> {"pm","eng","mfg", "Mechanical..","Hydraulic..","Electrical.."}
        cur.execute(f"SELECT ProjectID, ISNULL(HourType,0), SUM(Hours) FROM dbo.tblSpecHours "
                    f"WHERE ProjectID IN ({idlist}) GROUP BY ProjectID, HourType")
        for pid, ht, hrs in cur.fetchall():
            d = self._map.get(int(ht))
            h = float(hrs or 0)
            slot = det.setdefault(int(pid), {"pm": 0.0, "eng": 0.0, "mfg": 0.0})
            if d == "Project Management":
                slot["pm"] += h
            elif d in _ENG:
                slot["eng"] += h
                slot[d] = slot.get(d, 0.0) + h
            elif d == "Manufacturing":
                slot["mfg"] += h
            # 'Other'/residue: ignored (folded into view buckets)

        out = {}
        for pid in set(ids):
            a, e, m, matv = view.get(pid, (0.0, 0.0, 0.0, None))
            d = det.get(pid, {})
            # view wins per bucket; fall back to line-detail where the view is empty
            admin = a if a > 0 else d.get("pm", 0.0)
            eng = e if e > 0 else d.get("eng", 0.0)
            mfg = m if m > 0 else d.get("mfg", 0.0)
            # split Eng by line-detail proportions (default all to Mechanical if no detail)
            es = {k: d.get(k, 0.0) for k in _ENG}
            tot = sum(es.values())
            if tot > 0:
                mech = eng * es["Mechanical Engineering"] / tot
                hyd = eng * es["Hydraulic Engineering"] / tot
                elec = eng * es["Electrical Engineering"] / tot
            else:
                mech, hyd, elec = eng, 0.0, 0.0

            dh = {
                "Project Management": round(admin, 2),
                "Mechanical Engineering": round(mech, 2),
                "Hydraulic Engineering": round(hyd, 2),
                "Electrical Engineering": round(elec, 2),
                "Manufacturing": round(mfg, 2),
            }
            dh = {k: v for k, v in dh.items() if v}
            total = admin + eng + mfg
            out[pid] = Budget(
                project_id=pid,
                is_current=True,
                material_budget=matv,
                labour_budget_hours=(round(total, 2) if total else None),
                discipline_hours=dh,
            )
        log.info("built %d ETO budgets (view-anchored, detail fallback)", len(out))
        return out

    def get_current(self, project_id):
        return self.get_current_many([project_id]).get(int(project_id))
