# Project Console — Reporting DB Schema Design (budgets + PM entries)

**Owner:** Vijay Nair (IT) · **Drafted:** 2026-07-25
**Grounds on:** `REPORTING_SCHEMA_FRAMEWORK.md` (IT-owned Reporting schema, Cache/View/
ETL pattern, `tbl…`/`vw_<Category>_<Report>`/`<dataset>_sync.py` naming).
**Purpose:** give the Project Console manual data (budgets, PM entries) a governed home in the
Reporting schema so we get a **stable interface** (dashboard reads views, not spreadsheet
cells) and **versioning** (budget history + weekly PM history) — the foundation for the
future web UI.

---

## 1. Why a DB (the two problems it solves)

- **Interface stability.** Today the dashboard parses fixed spreadsheet cells (Budgets
  AW:BA, PM Entries row 12…). Any re-layout breaks it. Reading governed **views** decouples
  the dashboard from the entry surface — spreadsheet today, web UI tomorrow, same views.
- **Versioning.** Budgets change (change orders, re-baselines) and PM entries are weekly.
  A DB captures every version as a row — "what was 230219's mechanical budget in week 24
  vs week 29" becomes a query, not a lost overwrite.

This is a NEW use of the Reporting schema: not a cache of `dbo`, but the **system of record
for data that lives nowhere else** (the manual half). It slots cleanly into the framework.

---

## 2. Tables (Reporting schema, IT-owned)

### `Reporting.tblProjectBudget` — versioned budget header (SCD-2)
One row per project **per version**. A new version is written only when values change.
```
BudgetVersionID   INT IDENTITY PK
ProjectID         INT
EffectiveFrom     DATE            -- when this version took effect
EffectiveTo       DATE NULL       -- NULL = current
IsCurrent         BIT
Source            NVARCHAR(60)    -- 'Budgets.xlsx@2026-29' | 'WebUI' | 'ChangeOrder#123'
POShipDate        DATE
CustAgreedShipDate DATE
MaterialBudget    DECIMAL(14,2)
LabourBudgetHours DECIMAL(12,2)
PMHours           DECIMAL(12,2)   -- the 5 discipline roll-ups (Budgets 'Helpers' AW:BA)
MechanicalHours   DECIMAL(12,2)
ElectricalHours   DECIMAL(12,2)
HydraulicHours    DECIMAL(12,2)
ManufacturingHours DECIMAL(12,2)
OtherHours        DECIMAL(12,2)
CreatedAt         DATETIME DEFAULT GETDATE()
CreatedBy         NVARCHAR(60)
-- UNIQUE (ProjectID, EffectiveFrom); filtered index on (ProjectID) WHERE IsCurrent=1
```

### `Reporting.tblProjectBudgetDetail` — fine-grain budget (optional but recommended)
Preserves the Budgets tab's per-HourDescription detail (cols I:AU) so discipline roll-ups
and the crosswalk can be re-derived, and so a future UI can edit at that grain.
```
BudgetVersionID   INT FK → tblProjectBudget
HourDescription   NVARCHAR(60)
BudgetHours       DECIMAL(12,2)
-- PK (BudgetVersionID, HourDescription)
```

### `Reporting.tblProjectPMEntry` — weekly PM inputs (versioned by week natively)
```
PMEntryID         INT IDENTITY PK
ProjectID         INT
FiscalYear        INT
WeekNo            INT
YearWeekKey       INT             -- 202629
PlannedShipDate   DATE NULL       -- 2099 placeholder normalised to NULL on load
PercentComplete   DECIMAL(5,4)
LabourRunout      DECIMAL(6,4)
MaterialRunout    DECIMAL(6,4)
MaterialActual    DECIMAL(14,2)
MaterialBudget    DECIMAL(14,2)
TotalLineItems    INT NULL
LLTPOrdered … PartsOrderedLate  INT NULL   -- the 7 procurement counts
Delta1WkPercentDone DECIMAL(6,4) NULL
Delta1WkMaterial  DECIMAL(14,2) NULL
IncludeFlag       BIT
Rank              INT NULL
ReRank            INT NULL
CapturedAt        DATETIME DEFAULT GETDATE()
-- UNIQUE (ProjectID, YearWeekKey)
```

### `Reporting.tlkpDisciplineCrosswalk` — HourDescription → discipline (single source of truth)
```
HourDescription   NVARCHAR(60) PK
Discipline        NVARCHAR(40)      -- PM / Mechanical / Electrical / Hydraulic / Manufacturing / Other
```
Seeded from the Budgets tab grouping (`console_pack.derive_crosswalk_from_budgets`). BOTH
the budget roll-up AND the ETO actual-hours re-code read this table, so they can never drift.

---

## 3. Views + the Python bridge (no cross-DB links)

The Console DB has **no link to ETO** — Python is the only bridge (`console_store`, two
separate connections). So there is no cross-database view; actual labour by discipline is
computed in the engine (`console_engine` reads ETO live and applies the crosswalk loaded
from `tlkpDisciplineCrosswalk`). The store therefore holds only Console-side views:

- `Reporting.vw_Console_BudgetCurrent` — `WHERE IsCurrent = 1`; current budget per project.
- `Reporting.vw_Console_PMEntryLatest` — most-recent week per project (Include=1).
- `Reporting.vw_Console_ManualOverlay` — current budget + latest PM entry, one row per
  project. **The dashboard reads this (manual side); ETO actuals are joined in Python.**
- `Reporting.vw_Console_ProjectTrajectory` — the weekly history (see §7).

Why no cross-DB view: it kept the Console DB free of any vendor dependency (the login needs
no Production grant), and it makes the store swappable to Postgres/cloud for SaaS —
reimplement `console_store`, nothing else changes.

---

## 4. ETL — `console_sync.py` (framework §7 pattern)

Reads the spreadsheet's Budgets + PM Entries (via `console_pack.py`) and upserts:
- **Budgets:** compare incoming to `IsCurrent` row; if changed → close current
  (`EffectiveTo`, `IsCurrent=0`) and insert a new version (SCD-2). Unchanged → no-op.
- **Budget detail + crosswalk:** refresh from the tab.
- **PM entries:** upsert by `(ProjectID, YearWeekKey)` — idempotent; each week accrues.
Schedule: weekly after PMs update (e.g., Friday 17:00), before the executive report.

The spreadsheet **stays the PM entry point** — this just banks it into the DB each week.

---

## 5. Migration path (non-disruptive; honours "keep the spreadsheet as-is")

**Phase A — DB as reporting interface, fed from the spreadsheet.**
Stand up tables + views. `console_sync.py` loads the spreadsheet weekly. Dashboard switches
to read `Reporting.vw_Console_*`. Spreadsheet unchanged for PMs. *Immediate wins:* stable
interface, versioned history starts accruing, single source of truth. Fits inside the
"perfect reporting for 3–4 cycles" window as Cycle 3–4 infrastructure.

**Phase B — web UI writes to the DB.** The eventual UI INSERTs new budget versions / PM
entries straight into these tables; `console_sync` retires; spreadsheet is decommissioned.
Because the dashboard already reads the views, **the reporting side doesn't change** when the
entry surface flips. That's the payoff of doing the interface now.

---

## 6. Open decisions (need owner/infra input) — resolved 2026-07-25

1. **Where it lives + write access.** RESOLVED: separate customer-owned `Macrodyne_Reporting`
   database with its own writable service account; cross-DB read of `dbo` via the ETO synonym
   interface. Owned by a Macrodyne principal — never the vendor account.
2. **Timing.** RESOLVED: stand up now, as Cycle 3–4 infrastructure.
3. **Budget versioning grain.** RESOLVED: SCD-2 change-detected.
4. **Employee hierarchy dependency.** `tblEmployeeHierarchy` (Kronos) — needed only for
   Manager/Dept slicing on the Project Dashboard, not for the core.

---

## 7. History / trajectory layer — the prediction foundation

`Reporting.tblProjectWeeklySnapshot` (002_project_snapshot.sql) captures **one row per
project per week**: the budget version in effect, ETO actual hours/cost by discipline cut
at that week-end, and the PM progress (% done, run-outs, material). View
`vw_Console_ProjectTrajectory` exposes each project's full weekly series.

This turns the versioned history into a **training table** for future prediction models —
estimate-at-completion, budget-overrun risk, schedule slippage — the Layer-2 (forward
exposure) work. Two properties make it strong training data:

- **Budget trajectory** (SCD-2) records how each estimate evolved (change orders /
  re-baselines) — the model sees the plan moving, not just the final number.
- **Backfillable from ETO.** Because timecards are dated, actuals *as of week N* are
  recomputable (`TimeDate <= week-end`), so the whole history can be reconstructed on the
  first sync — every project's trajectory from week one, immediately available to model.

Population is a `console_sync` step (later): for each project × week, snapshot the bracketing
budget version + ETO actuals-to-date + that week's PM entry. Not built yet; the table and
view are in place so the history starts accruing as soon as population lands.
```
