"""
ProjectFinancials — a DERIVED entity: the net of the Budget's discipline allocation
against the DisciplineActuals. Not a source read — it composes two other entities
(Budget from the Console store, DisciplineActuals from ETO) into the budget-vs-actual
position per discipline and in total (consumed / remaining / variance), plus material.

The plan/denominator is the CONSOLE budget, never ETO's own estimate.
"""
from dataclasses import dataclass, field

from console.domain.budget import BudgetDAO
from console.domain.discipline_actuals import DisciplineActualsDAO
from console.infra.logging_config import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class DisciplineFinancial:
    discipline: str
    budget_hours: float | None
    actual_hours: float | None

    @property
    def consumed_pct(self):
        if self.budget_hours:                       # non-zero budget
            return round((self.actual_hours or 0.0) / self.budget_hours, 4)
        return None

    @property
    def remaining_hours(self):
        if self.budget_hours is None or self.actual_hours is None:
            return None
        return round(self.budget_hours - self.actual_hours, 2)


@dataclass
class ProjectFinancials:
    project_id: int
    disciplines: list = field(default_factory=list)   # list[DisciplineFinancial]
    labour_budget_hours: float | None = None
    labour_actual_hours: float | None = None
    material_budget: float | None = None
    material_actual: float | None = None        # Resource Consumption (headline) = ETO ActTotalMaterials
    material_committed: float | None = None      # Committed Spend = ETO purchased (costed) materials
    material_inventory: float | None = None      # material issued from stock
    material_payables: float | None = None       # other booked costs (AP / extra)

    @property
    def labour_consumed_pct(self):
        if self.labour_budget_hours:
            return round((self.labour_actual_hours or 0.0) / self.labour_budget_hours, 4)
        return None

    @property
    def material_consumed_pct(self):
        """Resource Consumption ÷ budget — the headline material %, ties to ETO's report."""
        if self.material_budget:
            return round((self.material_actual or 0.0) / self.material_budget, 4)
        return None

    @property
    def material_committed_pct(self):
        """Committed Spend (purchased material) ÷ budget — the cash-committed lens."""
        if self.material_budget:
            return round((self.material_committed or 0.0) / self.material_budget, 4)
        return None

    def discipline(self, name: str):
        return next((d for d in self.disciplines if d.discipline == name), None)


def net(budget, actuals, material_actual=None) -> ProjectFinancials:
    """Net one project's Budget against its DisciplineActuals → ProjectFinancials.
    Pure function (no I/O) so it's trivially testable. `budget` may be None (no plan);
    `actuals` may be None (no charges yet)."""
    pid = budget.project_id if budget else (actuals.project_id if actuals else None)
    disc_names = set()
    if budget:
        disc_names |= set(budget.discipline_hours)
    if actuals:
        disc_names |= set(actuals.by_discipline)
    lines = []
    for name in disc_names:
        b = budget.budget_for(name) if budget else None
        a = actuals.hours(name) if actuals else None
        lines.append(DisciplineFinancial(name, b, a))
    lines.sort(key=lambda d: d.discipline)
    return ProjectFinancials(
        project_id=pid,
        disciplines=lines,
        labour_budget_hours=(budget.labour_budget_hours if budget else None),
        labour_actual_hours=(actuals.total_hours() if actuals else None),
        material_budget=(budget.material_budget if budget else None),
        material_actual=material_actual,
    )


class ProjectFinancialsService:
    """Assembles ProjectFinancials by composing the Budget and DisciplineActuals DAOs.
    This is where the derived entity is built — the DAOs stay single-entity."""

    def __init__(self, budget_dao: BudgetDAO, actuals_dao: DisciplineActualsDAO):
        self._budgets = budget_dao
        self._actuals = actuals_dao

    def for_projects(self, project_ids, material_actuals: dict = None) -> dict:
        """{project_id: ProjectFinancials}. `material_actuals` optional {pid: $}."""
        material_actuals = material_actuals or {}
        budgets = self._budgets.get_current_many(project_ids)
        actuals = self._actuals.for_projects(project_ids)
        out = {}
        for pid in {int(p) for p in project_ids}:
            out[pid] = net(budgets.get(pid), actuals.get(pid), material_actuals.get(pid))
        log.info("netted financials for %d projects", len(out))
        return out
