"""
Pattern verification for the layered architecture (no DB).
Exercises: DO construction, the pure derived net() (ProjectFinancials), the
DisciplineFinancial math, a DAO happy-path via a fake cursor, and a DAO error path
mapping a driver failure to a typed ConsoleError.
"""
from console.domain.budget import Budget, BudgetLine, BudgetDAO
from console.domain.discipline_actuals import DisciplineActual, ProjectDisciplineActuals
from console.domain.project_financials import net, ProjectFinancials, DisciplineFinancial
from console.domain.crosswalk import CrosswalkDAO
from console.infra.errors import StoreReadError


# ── 1. Derived net(): Budget allocation ⊗ DisciplineActuals ─────────────────────
budget = Budget(
    project_id=230219,
    budget_version_id=7,
    labour_budget_hours=8429,
    material_budget=2607952,
    discipline_hours={"Project Management": 260, "Mechanical Engineering": 1640,
                      "Electrical Engineering": 1732, "Hydraulic Engineering": 572,
                      "Manufacturing": 4225},
    detail=[BudgetLine("Management", 200), BudgetLine("Mechanical Engineering", 1500)],
)
actuals = ProjectDisciplineActuals(
    project_id=230219,
    by_discipline={
        "Project Management": DisciplineActual("Project Management", 234, 20000),
        "Mechanical Engineering": DisciplineActual("Mechanical Engineering", 1800, 160000),
        "Electrical Engineering": DisciplineActual("Electrical Engineering", 1560, 140000),
        "Hydraulic Engineering": DisciplineActual("Hydraulic Engineering", 600, 55000),
        "Manufacturing": DisciplineActual("Manufacturing", 3000, 260000),
    },
)

fin = net(budget, actuals, material_actual=2393609)
assert isinstance(fin, ProjectFinancials) and fin.project_id == 230219

mech = fin.discipline("Mechanical Engineering")
assert mech.budget_hours == 1640 and mech.actual_hours == 1800
assert mech.consumed_pct == round(1800 / 1640, 4)              # over budget
assert mech.remaining_hours == round(1640 - 1800, 2) == -160.0  # negative = overrun
# labour total = sum of actual discipline hours vs Console labour budget
assert fin.labour_actual_hours == 234 + 1800 + 1560 + 600 + 3000
assert fin.labour_consumed_pct == round(fin.labour_actual_hours / 8429, 4)
assert fin.material_consumed_pct == round(2393609 / 2607952, 4)
print("derived net() OK — ProjectFinancials composed from Budget + DisciplineActuals")

# ── 2. Edge cases: no budget / no actuals / zero budget ─────────────────────────
assert net(None, actuals).discipline("Manufacturing").consumed_pct is None   # no budget → None
assert net(budget, None).labour_actual_hours is None                          # no charges
zero = DisciplineFinancial("X", budget_hours=0, actual_hours=50)
assert zero.consumed_pct is None                                              # no div-by-zero
print("edge cases OK — no budget / no actuals / zero-budget handled")


# ── 3. DAO happy path + error path via a fake cursor ────────────────────────────
class FakeCursor:
    def __init__(self, rows, fail=False):
        self._rows, self._fail = rows, fail
        self.description = [("HourDescription",), ("Discipline",)]
    def execute(self, *a, **k):
        if self._fail:
            raise RuntimeError("ODBC: connection reset")
    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, rows, fail=False):
        self._c = FakeCursor(rows, fail)
    def cursor(self):
        return self._c


xmap = CrosswalkDAO(FakeConn([("Management", "Project Management"),
                              ("Mechanical Engineering", "Mechanical Engineering")])).load_map()
assert xmap["Management"] == "Project Management"
print("CrosswalkDAO.load_map OK via fake cursor")

try:
    CrosswalkDAO(FakeConn([], fail=True)).load_map()
    raise SystemExit("expected StoreReadError")
except StoreReadError:
    print("DAO error path OK — driver failure mapped to StoreReadError (typed, logged)")

# ── 4. BudgetDAO row→DO mapping (no cursor) ─────────────────────────────────────
cols = ["ProjectID", "BudgetVersionID", "IsCurrent", "POShipDate", "MaterialBudget",
        "LabourBudgetHours", "PMHours", "MechanicalHours"]
row = [230219, 7, 1, None, 2607952, 8429, 260, 1640]
b = BudgetDAO(None)._header_to_do(row, cols)
assert b.project_id == 230219 and b.budget_for("Mechanical Engineering") == 1640
print("BudgetDAO row→DO mapping OK")

print("\nAll pattern assertions passed.")
