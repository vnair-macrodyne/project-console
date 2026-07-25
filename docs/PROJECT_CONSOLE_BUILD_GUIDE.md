# Project Console Executive Dashboard — Build & Run Guide

**Owner:** Vijay Nair (IT) · **Updated:** 2026-07-24
**Modules:** `console_dashboard.py`, `console_engine.py`, `console_budgets.py`,
`console_feed.py` · **Companions:** `CARPEDIA_DASHBOARD_SPEC.md`, `CARPEDIA_PHASE_PLAN.md`

The Phase-1 last-mile: automated ETO numbers land in the Executive Dashboard where
management reads them, with a single PM entry point (the Budgets tab) for the manual
half. Validated live on 230219 (Labour 124.9% hrs / Material 92.2%, ties to the
reconciliation).

---

## The operating model — ETO seeds, PM splits, ETO reads back

```
   ETO  ──seed──▶  Budgets (Input) sheet  ──PM fills──▶  Budgets (Input) sheet
    │              (project list, 3-bucket        (Eng split: Mech/Hyd/Elec,
    │               est hrs, totals)               ship dates)
    │                                                        │
    └──────────── actuals (labour/material/2-wk) ───────────┤
                                                             ▼
                                                Executive Dashboard (Auto)
```

The **only** manual input is the Budgets (Input) sheet, and even there ETO pre-fills
everything it knows (project list, Admin/Eng/Mfg estimate hours, total budget hours;
PM & Manufacturing budget columns pre-seeded). The PM's real job is splitting the
Engineering bucket into Mechanical / Hydraulic / Electrical and entering ship dates.
A `Δ vs ETO Total` column flags a mis-key live.

---

## Where each dashboard cell comes from

| Block | Metric | Source |
|-------|--------|--------|
| **Schedule** | P.O. / Cust-Agreed / Planned ship dates, % Done | Budgets (Input) — PM |
| | Slippage (days) | derived = Planned − Cust-Agreed |
| **Budget** | % Consumed Labour (**hours** — lead metric) | ETO — `LabPctHrs` |
| | % Consumed Labour ($) | ETO — `LabPctCost` (diverges by design where budget is loaded-rate) |
| | % Consumed Material | ETO — `MatPct` |
| | Run-out Labour | derived = Labour%(hrs) ÷ %Done |
| **2-Week Delta** | Labour Hrs (last 2 wks) | ETO — lean timecard aggregate |
| | % Done delta, Material Spend delta | overlay CSV (PM Entries; Phase 3A for material) |
| **Labour** | % per discipline (PM/Mech/Hyd/Elec/Mfg) — **hours** | ETO actual hrs ÷ Budgets (Input) budget hrs |
| **Procurement** | LLTP line-item lateness counts | overlay CSV (Phase 3A) |

**Discipline block is HOURS** (actual hrs ÷ budget hrs), not dollars — this matches
the manual dashboard, keeps the whole sheet on the lead-on-hours principle, and avoids
the loaded-rate distortion. The old $-basis divided by sparse/zero budget-$ by hour
type and was unreliable. Budget hours per discipline are **not in ETO** at 6-discipline
grain (only Admin/Eng/Mfg) — that split is authored on the Budgets tab.

---

## Run — the three-step loop

Put the four modules next to the deployed suite (so imports resolve). Then:

```bash
# 1. Seed the Budgets (Input) PM entry form from ETO
python console_dashboard.py --make-budgets \
    --projects 230219,240033,240148,240040,250250,240218,250217,240154,240088,220154
#    → Project Console_Budgets_Input.xlsx   (or <workbook>_BUDGETS.xlsx if --workbook given)

# 2. PM fills the YELLOW cells: split Engineering into Mech/Hyd/Elec, enter ship
#    dates, keep 'Δ vs ETO Total' near 0. Save.

# 3. Build the dashboard off the filled file
python console_dashboard.py --workbook Project Console_Budgets_Input.xlsx \
    --projects 230219,240033,240148,240040,250250,240218,250217,240154,240088,220154
#    → Project Console_Budgets_Input_AUTO.xlsx  (Budgets (Input) + Executive Dashboard (Auto))
```

To fold into the real management pack instead, point `--workbook` at the pack's full
path in both steps: `--make-budgets` adds the seeded Budgets (Input) sheet to a copy;
re-running reads it back and adds the dashboard sheet, leaving every other tab intact.
PM entries **carry forward** across re-seeds — re-running `--make-budgets` never wipes
typed values.

Other flags: `--standalone` (fresh one-sheet dashboard, no pack); `--overlay xxx.csv`
(layer the PM-Entries CSV — procurement, 2-wk deltas — on top of the Budgets sheet);
`--make-overlay-template` (blank CSV for those remaining fields).

---

## Validation & discovery status

- **Column verification done** (`console_diag_cols.py`, `console_diag_hours.py`):
  `vwTimecards` pre-resolves `DeptName`, `PDescription`, `SDescription`, `EmpNumber`,
  `TimeDate`, `HourTime`, `HourRate`, `HourFactor`; the Labor Data feed's `tblSpec`
  join was dropped (SDescription is on the view); `SpecID` is a float (cleaned).
  No `TODO(verify)` columns remain.
- **230219 ties out** on the project-level budget block (124.9% hrs / 92.2% material).
- **Open:** confirm the discipline hours read sensibly once real PM budgets are entered;
  wire the Procurement + 2-wk material blocks onto Phase 3A PO views to retire more of
  the CSV overlay.

---

## Files

| File | Role |
|------|------|
| `console_dashboard.py` | Assembly + styled writer + CLI (`--make-budgets`, `--standalone`, `--overlay`) |
| `console_budgets.py` | Budgets (Input) PM entry form — seed from ETO + read back |
| `console_engine.py` | ETO engine: est-vs-act summary, actual hrs by discipline, 2-wk labour |
| `console_feed.py` | Asset Re-Code crosswalk + Labor Data feed (finalised to live columns) |
| `console_diag_cols.py`, `console_diag_hours.py` | Read-only schema probes |
| `test_dashboard.py` | Synthetic verification (no DB): hours basis + Budgets loop |
