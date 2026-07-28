"""
EtoBudgetDAO — the project BUDGET sourced from ETO (the authoritative estimate),
replacing the manual Console store as the dashboard's budget denominator.

Owner decision 2026-07-27: budgets come from ETO. Per-discipline budget HOURS are
tblSpecHours.Hours (all rows = ETO's headline estimate) grouped by HourType and mapped
to the 6 disciplines via the HourType->discipline crosswalk (console.domain.hourtype_map,
anchored to ETO's department — reconciles exactly to the 3-bucket estimate). Material
budget $ is EstTotalMaterials from vwProjectActualsVSEstimates.

Schedule (ship dates, % done) is NOT in ETO — it stays the manual overlay, so those
Budget fields are left None here; the dashboard reads them from the overlay as before.

Interface parity: exposes get_current_many(project_ids) -> {pid: Budget}, the same shape
as console.domain.budget.BudgetDAO, so ProjectFinancialsService is unchanged — only the
DAO it is handed changes. Read-only against ETO like everything else.
"""
from console.domain.budget import Budget
from console.infra.logging_config import get_logger

log = get_logger(__name__)


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


class EtoBudgetDAO:
    def __init__(self, eto_conn, hourtype_map: dict):
        """hourtype_map: {HourType(int): discipline}. Unknown / HourType=0 lines fall to
        'Other' (the breadth check confirms this residue is ~0 on real projects)."""
        self._eto = eto_conn
        self._map = hourtype_map or {}

    def get_current_many(self, project_ids) -> dict:
        ids = [int(p) for p in (project_ids or [])]
        if not ids:
            return {}
        idlist = ",".join(str(p) for p in ids)
        cur = self._eto.cursor()

        # per-discipline budget hours: tblSpecHours grouped by HourType -> discipline
        disc = {}
        cur.execute(f"SELECT ProjectID, ISNULL(HourType,0), SUM(Hours) "
                    f"FROM dbo.tblSpecHours WHERE ProjectID IN ({idlist}) "
                    f"GROUP BY ProjectID, HourType")
        for pid, ht, hrs in cur.fetchall():
            pid = int(pid)
            d = self._map.get(int(ht), "Other")
            slot = disc.setdefault(pid, {})
            slot[d] = slot.get(d, 0.0) + float(hrs or 0)

        # material budget $ from the estimate view
        cur.execute(f"SELECT ProjectID, EstTotalMaterials FROM dbo.vwProjectActualsVSEstimates "
                    f"WHERE ProjectID IN ({idlist})")
        mat = {int(r[0]): _f(r[1]) for r in cur.fetchall()}

        out = {}
        for pid in set(ids):
            dh = {k: round(v, 2) for k, v in disc.get(pid, {}).items() if v}
            out[pid] = Budget(
                project_id=pid,
                is_current=True,
                material_budget=mat.get(pid),
                labour_budget_hours=(round(sum(dh.values()), 2) if dh else None),
                discipline_hours=dh,
            )
        log.info("built %d ETO budgets", len(out))
        return out

    def get_current(self, project_id):
        return self.get_current_many([project_id]).get(int(project_id))
