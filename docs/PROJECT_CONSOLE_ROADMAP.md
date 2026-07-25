# Project Console — Near-Term Reporting Roadmap & Direction

**Owner:** Vijay Nair (IT) · **Set:** 2026-07-24
**Companion to:** `CARPEDIA_PHASE_PLAN.md` (program north star),
`PROJECT_CONSOLE_BUILD_GUIDE.md` (how the build runs).

---

## Direction (owner's call, 2026-07-24)

**Perfect the REPORTING side for the next 3–4 cycles, then re-think the INPUT side.**

- The **budgeting spreadsheet stays as-is** for now. The engine READS the existing
  Budgets and PM Entries tabs the way PMs already maintain them — it does not replace
  or re-lay-out them.
- The seeded "Budgets (Input)" form (`console_budgets.py`) is **deferred**. It is
  kept as a prototype of the *future* input UI's data contract, not used to drive the
  current workflow.
- **Later phase — input redesign:** enhance budgeting to a **web-based UI**. The
  enabler for that is **storing budget info and versioning it** (change orders /
  re-baselines tracked over time). Candidate long-term home: `Reporting.tblProjectEstimates`
  (phase plan Q). NOTE 2026-07-25: this DB layer is now BUILT (Macrodyne_Reporting).

## The architecture we're building to (both dashboards)

Two manual entry points, ETO for all actuals, feeding BOTH dashboards:

- **Budgets tab** — the *plan*: budget hours per discipline, ship dates.
- **PM Entries tab** — *progress & material*: % done, 2-week deltas, material
  actual vs budget.
- **ETO** — all *actuals*: labour (hrs + $, by discipline), PO/Materials (spend,
  commitments, lateness).
- **Consumers:** Executive Dashboard (portfolio scorecard) + Project Dashboard
  (per-project detail + charts). Same inputs, two presentations.

## The 3–4 cycles

1. **Cycle 1 — read existing tabs as-is.** DONE. Map the real Budgets + PM Entries layouts
   and read them directly, so the Executive Dashboard is fully fed by the two entry points
   + ETO. Crosswalk aligned (39/39). Discipline block validated (Δ=0).
2. **Cycle 2 — Project Dashboard.** Per-project detail + charts off the same inputs.
3. **Cycle 3 — PO/Materials (Phase 3A).** Wire `eto_povalue` / `eto_exceptions` into
   both dashboards: material actual, 2-week material spend, procurement/LLTP lateness —
   retiring most of the manual CSV overlay.
4. **Cycle 4 — validate + polish + version-capture.** Portfolio-wide reconciliation,
   ranking/formatting/charts, scheduled distribution, pin the active-capital set. The
   **budget-snapshot/versioning** is delivered via the Reporting DB (SCD-2).

## What is NOT in scope now

Input-side web UI (deferred). Release-signal / Layer-2 forward-exposure work stays parked
until reporting is solid (the `MfgBegin` / `ProcessScheduleDetailID` population probe is the
eventual unlock).

## Prediction foundation (data now, models later)

The Console DB banks a **weekly trajectory** per project (`tblProjectWeeklySnapshot`):
budget-in-effect + ETO actuals-as-of-week + PM progress. This is deliberate — the versioned
history is the **training data** for future prediction models (estimate-at-completion,
overrun risk, slippage), which is the Layer-2 payoff. Backfillable from ETO's dated
timecards, so history starts full, not empty. Models come later; the data starts accruing now.

## Current state carried in

Product renamed **Project Console → Project Console** (code `console_*`, DB views `vw_Console_*`,
branding via tenant profile). Executive Dashboard reads the real Budgets + PM Entries +
ETO; discipline block on the HOURS basis (actual hrs ÷ budget hrs); 230219 validated
(124.9% hrs / 92.2% material). Reporting DB (`Macrodyne_Reporting`) + ETO synonym interface
built; `console_sync` dry-run validated (21 budgets, 22 weeks PM, 39 crosswalk). Product
made lift-and-shift ready via `console_config.TenantProfile`. Next: run 001/002, load the
DB, point the dashboard at the Reporting views.
