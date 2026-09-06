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

        # 2) tblSpecHours line-detail, mapped to buckets via the HourType→discipline crosswalk.
        # This is the AUTHORITATIVE discipline split (see the loop below): it honors the deliberate
        # re-codes — notably shop-floor Start-Up → Manufacturing (sql/012) — that ETO's own
        # HourDepartment bucketing in the rolled-up view does NOT.
        det = {}   # pid -> {"pm","eng","mfg","other", "Mechanical..","Hydraulic..","Electrical.."}
        cur.execute(f"SELECT ProjectID, ISNULL(HourType,0), SUM(Hours) FROM dbo.tblSpecHours "
                    f"WHERE ProjectID IN ({idlist}) GROUP BY ProjectID, HourType")
        for pid, ht, hrs in cur.fetchall():
            d = self._map.get(int(ht))
            h = float(hrs or 0)
            slot = det.setdefault(int(pid), {"pm": 0.0, "eng": 0.0, "mfg": 0.0, "other": 0.0})
            if d == "Project Management":
                slot["pm"] += h
            elif d in _ENG:
                slot["eng"] += h
                slot[d] = slot.get(d, 0.0) + h
            elif d == "Manufacturing":
                slot["mfg"] += h
            else:
                slot["other"] += h        # NC / rework / unmapped — a real 6th bucket, kept not dropped

        out = {}
        for pid in set(ids):
            a, e, m, matv = view.get(pid, (0.0, 0.0, 0.0, None))
            d = det.get(pid, {})
            # TOTAL is anchored to ETO's rolled-up estimate — the authoritative magnitude, so a
            # project whose spec-hour detail is thin/incomplete is never understated (fall back to
            # detail only when the estimate is empty). But the Eng/Mfg BOUNDARY is taken from the
            # spec-hour detail via the crosswalk, so the deliberate re-codes (e.g. shop-floor
            # Start-Up → Manufacturing, sql/012) are honored instead of ETO's own HourDepartment
            # bucketing. Net: correct totals AND correct Eng/Mfg line — what the old view-anchored
            # code and a pure detail sum each got only half-right.
            admin = a if a > 0 else d.get("pm", 0.0)
            pool = (e + m) if (e + m) > 0 else (d.get("eng", 0.0) + d.get("mfg", 0.0))
            prod = {
                "Mechanical Engineering": d.get("Mechanical Engineering", 0.0),
                "Electrical Engineering": d.get("Electrical Engineering", 0.0),
                "Hydraulic Engineering": d.get("Hydraulic Engineering", 0.0),
                "Manufacturing": d.get("mfg", 0.0),
            }
            ptot = sum(prod.values())
            if ptot > 0:
                split = {k: pool * v / ptot for k, v in prod.items()}   # crosswalk proportions
            else:
                # no productive spec detail — keep ETO's own Eng/Mfg split (all Eng → Mechanical)
                split = {"Mechanical Engineering": e, "Electrical Engineering": 0.0,
                         "Hydraulic Engineering": 0.0, "Manufacturing": m}

            dh = {"Project Management": round(admin, 2)}
            for k in ("Mechanical Engineering", "Electrical Engineering",
                      "Hydraulic Engineering", "Manufacturing"):
                dh[k] = round(split[k], 2)
            dh = {k: v for k, v in dh.items() if v}
            total = admin + pool
            out[pid] = Budget(
                project_id=pid,
                is_current=True,
                material_budget=matv,
                labour_budget_hours=(round(total, 2) if total else None),
                discipline_hours=dh,
            )
        log.info("built %d ETO budgets (estimate total, crosswalk Eng/Mfg split)", len(out))
        return out

    def get_current(self, project_id):
        return self.get_current_many([project_id]).get(int(project_id))
