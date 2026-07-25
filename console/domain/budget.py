"""
Budget — a project's versioned plan (Console entity).
Assembled from two Console tables: tblProjectBudget (header, incl. the discipline
allocation roll-ups) + tblProjectBudgetDetail (fine-grain hours). One DO per project.
"""
from dataclasses import dataclass, field
from datetime import date

from console.infra.errors import StoreReadError, StoreWriteError
from console.infra.logging_config import get_logger

log = get_logger(__name__)

# Console discipline roll-up columns (header) → discipline name
_HEADER_DISCIPLINE = {
    "PMHours": "Project Management",
    "MechanicalHours": "Mechanical Engineering",
    "ElectricalHours": "Electrical Engineering",
    "HydraulicHours": "Hydraulic Engineering",
    "ManufacturingHours": "Manufacturing",
    "OtherHours": "Other",
}


@dataclass(frozen=True)
class BudgetLine:
    """One fine-grain budget line (a HourDescription's budgeted hours)."""
    hour_description: str
    budget_hours: float


@dataclass
class Budget:
    """A project's current budget version + its discipline allocation."""
    project_id: int
    budget_version_id: int | None = None
    effective_from: date | None = None
    is_current: bool = True
    po_ship_date: date | None = None
    cust_agreed_ship_date: date | None = None
    material_budget: float | None = None
    labour_budget_hours: float | None = None
    discipline_hours: dict = field(default_factory=dict)   # discipline -> budgeted hours
    detail: list = field(default_factory=list)             # list[BudgetLine]

    def budget_for(self, discipline: str):
        """Budgeted hours for a discipline (None if not allocated)."""
        return self.discipline_hours.get(discipline)


class BudgetDAO:
    """All SQL for the Budget entity."""

    def __init__(self, console_conn):
        self._conn = console_conn

    def _header_to_do(self, row, cols) -> Budget:
        d = dict(zip(cols, row))
        return Budget(
            project_id=int(d["ProjectID"]),
            budget_version_id=d.get("BudgetVersionID"),
            effective_from=d.get("EffectiveFrom"),
            is_current=bool(d.get("IsCurrent", 1)),
            po_ship_date=d.get("POShipDate"),
            cust_agreed_ship_date=d.get("CustAgreedShipDate"),
            material_budget=_f(d.get("MaterialBudget")),
            labour_budget_hours=_f(d.get("LabourBudgetHours")),
            discipline_hours={disc: _f(d.get(col))
                              for col, disc in _HEADER_DISCIPLINE.items()
                              if d.get(col) is not None},
        )

    def get_current_many(self, project_ids) -> dict:
        """{project_id: Budget} for the current version of each project, with detail."""
        if not project_ids:
            return {}
        ids = ",".join(str(int(p)) for p in project_ids)
        try:
            cur = self._conn.cursor()
            cur.execute(f"SELECT * FROM Reporting.vw_Console_BudgetCurrent "
                        f"WHERE ProjectID IN ({ids})")
            cols = [c[0] for c in cur.description]
            budgets = {}
            for row in cur.fetchall():
                b = self._header_to_do(row, cols)
                budgets[b.project_id] = b
            self._attach_detail(cur, budgets)
            log.info("loaded %d current budgets", len(budgets))
            return budgets
        except Exception as e:
            log.error("budget load failed: %s", e)
            raise StoreReadError("Failed to load current budgets") from e

    def get_current(self, project_id):
        return self.get_current_many([project_id]).get(int(project_id))

    def _attach_detail(self, cur, budgets: dict):
        vids = [b.budget_version_id for b in budgets.values() if b.budget_version_id]
        if not vids:
            return
        by_vid = {b.budget_version_id: b for b in budgets.values()}
        cur.execute("SELECT BudgetVersionID, HourDescription, BudgetHours "
                    "FROM Reporting.tblProjectBudgetDetail "
                    f"WHERE BudgetVersionID IN ({','.join(str(int(v)) for v in vids)})")
        for vid, hd, hrs in cur.fetchall():
            b = by_vid.get(vid)
            if b is not None:
                b.detail.append(BudgetLine(hd, _f(hrs)))

    def upsert_version(self, budget: Budget, effective: date, source: str,
                       created_by: str = "console") -> int:
        """SCD-2 upsert: new version only when values changed. Returns BudgetVersionID."""
        try:
            cur = self._conn.cursor()
            cur.execute("UPDATE Reporting.tblProjectBudget SET IsCurrent=0, EffectiveTo=? "
                        "WHERE ProjectID=? AND IsCurrent=1", effective, budget.project_id)
            dh = budget.discipline_hours
            cur.execute(
                "INSERT INTO Reporting.tblProjectBudget(ProjectID,EffectiveFrom,IsCurrent,Source,"
                "POShipDate,CustAgreedShipDate,MaterialBudget,LabourBudgetHours,PMHours,"
                "MechanicalHours,ElectricalHours,HydraulicHours,ManufacturingHours,OtherHours,CreatedBy) "
                "OUTPUT INSERTED.BudgetVersionID VALUES(?,?,1,?,?,?,?,?,?,?,?,?,?,?,?)",
                budget.project_id, effective, source, budget.po_ship_date,
                budget.cust_agreed_ship_date, budget.material_budget, budget.labour_budget_hours,
                dh.get("Project Management"), dh.get("Mechanical Engineering"),
                dh.get("Electrical Engineering"), dh.get("Hydraulic Engineering"),
                dh.get("Manufacturing"), dh.get("Other"), created_by)
            vid = cur.fetchone()[0]
            for line in budget.detail:
                cur.execute("INSERT INTO Reporting.tblProjectBudgetDetail"
                            "(BudgetVersionID,HourDescription,BudgetHours) VALUES(?,?,?)",
                            vid, line.hour_description, line.budget_hours)
            self._conn.commit()
            log.info("budget v%s written for project %s", vid, budget.project_id)
            return vid
        except Exception as e:
            self._conn.rollback()
            log.error("budget upsert failed for %s: %s", budget.project_id, e)
            raise StoreWriteError(f"Failed to write budget for project {budget.project_id}") from e


def _f(x):
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None
