"""
EtoBudgetDAO — the project BUDGET sourced from ETO (the authoritative estimate),
replacing the manual Console store as the dashboard's budget denominator.

Owner decision 2026-07-27: budgets come from ETO.

SOURCING (refined 2026-07-27 after the breadth check):
  * The 3-bucket estimate — Admin / Eng / Mfg hours + material $ — comes from
    vwProjectActualsVSEstimates, ETO's authoritative rolled-up estimate (the number the
    dashboard's % consumed has always reconciled to). We anchor totals here so every
    project reconciles, including the ~4% of (mostly older) projects whose tblSpecHours
    line-detail doesn't sum to the rolled-up estimate, and the projects carrying legacy
    HourType ids that aren't in the current tlkpHourTypes lookup.
  * tblSpecHours is used ONLY to split the Eng bucket into Mechanical / Electrical /
    Hydraulic, via the HourType->discipline crosswalk (console.domain.hourtype_map,
    anchored to ETO's department). Eng total is taken from the view and distributed by
    the proportions of the mapped Eng-HourType hours. Where a project has Eng hours but
    no Eng line-detail, the Eng total defaults to Mechanical (flagged by the breadth
    check as a fallback).

  Mapping:  PM = Admin ; Manufacturing = Mfg ; Mech/Elec/Hyd = Eng * split proportions.
  This reconciles PM==Admin, Mech+Elec+Hyd==Eng, Mfg==Mfg BY CONSTRUCTION.

Schedule (ship dates, % done) is NOT in ETO — it stays the manual overlay, so those
Budget fields are left None here; the dashboard reads them from the overlay as before.

Interface parity: get_current_many(project_ids) -> {pid: Budget}, the same shape as
console.domain.budget.BudgetDAO, so ProjectFinancialsService is unchanged — only the DAO
it is handed changes. Read-only against ETO like everything else.
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
        """hourtype_map: {HourType(int): discipline}. Only the Eng-bucket entries
        (mapping to Mechanical/Electrical/Hydraulic) are used, to split ETO's Eng total."""
        self._eto = eto_conn
        self._map = hourtype_map or {}

    def get_current_many(self, project_ids) -> dict:
        ids = [int(p) for p in (project_ids or [])]
        if not ids:
            return {}
        idlist = ",".join(str(p) for p in ids)
        cur = self._eto.cursor()

        # 1) authoritative 3-bucket estimate + material $ (the anchor)
        view = {}
        cur.execute(f"SELECT ProjectID, ISNULL(EstAdminHours,0), ISNULL(EstEngHours,0), "
                    f"ISNULL(EstMfgHours,0), EstTotalMaterials "
                    f"FROM dbo.vwProjectActualsVSEstimates WHERE ProjectID IN ({idlist})")
        for pid, a, e, m, matv in cur.fetchall():
            view[int(pid)] = (float(a or 0), float(e or 0), float(m or 0), _f(matv))

        # 2) Eng-bucket split proportions from tblSpecHours (mapped Eng HourTypes only)
        split = {}
        cur.execute(f"SELECT ProjectID, ISNULL(HourType,0), SUM(Hours) FROM dbo.tblSpecHours "
                    f"WHERE ProjectID IN ({idlist}) GROUP BY ProjectID, HourType")
        for pid, ht, hrs in cur.fetchall():
            d = self._map.get(int(ht))
            if d in _ENG:
                s = split.setdefault(int(pid), {})
                s[d] = s.get(d, 0.0) + float(hrs or 0)

        out = {}
        for pid in set(ids):
            a, e, m, matv = view.get(pid, (0.0, 0.0, 0.0, None))
            es = split.get(pid, {})
            tot = sum(es.values())
            if tot > 0:
                mech = e * es.get("Mechanical Engineering", 0.0) / tot
                hyd = e * es.get("Hydraulic Engineering", 0.0) / tot
                elec = e * es.get("Electrical Engineering", 0.0) / tot
            else:
                mech, hyd, elec = e, 0.0, 0.0   # no Eng detail -> default whole Eng to Mechanical

            dh = {
                "Project Management": round(a, 2),
                "Mechanical Engineering": round(mech, 2),
                "Hydraulic Engineering": round(hyd, 2),
                "Electrical Engineering": round(elec, 2),
                "Manufacturing": round(m, 2),
            }
            dh = {k: v for k, v in dh.items() if v}   # drop zeros -> blank on the dashboard
            total = a + e + m
            out[pid] = Budget(
                project_id=pid,
                is_current=True,
                material_budget=matv,
                labour_budget_hours=(round(total, 2) if total else None),
                discipline_hours=dh,
            )
        log.info("built %d ETO budgets (view-anchored)", len(out))
        return out

    def get_current(self, project_id):
        return self.get_current_many([project_id]).get(int(project_id))
