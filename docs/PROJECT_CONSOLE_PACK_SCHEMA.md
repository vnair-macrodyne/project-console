# Project Console Management Pack — Real Tab Schema (verified)

**Verified against the live pack 2026-07-25** (`Macrodyne Executive Dashboard.xlsx`).
Reader module: `console_pack.py`. This is the canonical map of the two manual entry
points — read them, don't reconstruct.

Sheets: Guide · Executive Dashboard (23×37) · Project Dashboard (90×42) ·
PM Entries (501×28) · Labor Data (50000×15) · Budgets (101×56) ·
Executive Dashboard V2 · Data Validation · Calculations · Worksheet.

---

## Budgets tab (101×56) — the *plan*

Group headers row 4, column headers row 5, **data from row 6**. One row per project.

| Col | # | Field |
|-----|---|-------|
| B | 2 | Project ID |
| C | 3 | Project |
| D | 4 | PO Ship Date |
| E | 5 | Customer Agreed Ship Date |
| F | 6 | Late Penalty? |
| H | 8 | Materials Budget — Total |
| I–T | 9–20 | **Project Management** detail (Customer Support, Management, Project Coordination, Training, Boring Mill Maintenance, **Electrical Procurement**, Housekeeping, Miscellaneous, Production Meeting, Purchasing, Quality Management/ISO, Sales) |
| U–V | 21–22 | **Mechanical Engineering** (Mechanical Engineering, Manuals) |
| W–Y | 23–25 | **Electrical Engineering** (Electrical Engineering, Programming, Shop Start-Up) |
| Z–AA | 26–27 | **Hydraulic Engineering** (Hydraulic Engineering, Shop Start-Up) |
| AB–AQ | 28–43 | **Manufacturing** detail (incl. Hydraulic Field Service) |
| AR–AU | 44–47 | **Other** (the four NC / Non-Conformance types) |
| **AW–BA** | **49–53** | **Helpers — discipline roll-ups**: PM / Mechanical / Electrical / Hydraulic / Manufacturing ← *dashboard budget denominators* |
| BB | 54 | Others, Labor |
| BC | 55 | Total, Material |
| BD | 56 | Total, Labor |

**The Budgets column grouping IS the authoritative HourDescription→discipline
crosswalk** (`console_pack.derive_crosswalk_from_budgets`). Diffed vs the actuals
crosswalk (`console_feed.DISCIPLINE_MAP`): 37 of 39 agreed; two corrected 2026-07-25 to
match the Budgets tab (source of truth):
- **Electrical Procurement → Project Management** (was Electrical Engineering).
- **Hydraulic Field Service → Manufacturing** (was missing).

Now fully aligned, so per-discipline actual (numerator) and budget (denominator) use
identical groupings.

---

## PM Entries tab (501×28) — *progress & material*, weekly time series

Header row 12, **data from row 13**. One row per project **per week** (this is the
history the future budget-versioning builds on). Week selector: **C8 "Front Page
Selection"** (currently `2026-29`); the dashboard takes that week's rows.

| Col | # | Field |
|-----|---|-------|
| B | 2 | Project ID |
| C | 3 | Client |
| D/E | 4/5 | Year / Week # |
| F | 6 | Planned Ship Date (`2099` = PM placeholder for TBD → treated as blank) |
| G | 7 | % Done |
| H | 8 | Labour run-out % |
| I | 9 | Material run-out % |
| J | 10 | Total Material Consumption (actual $) |
| K–Q | 11–17 | Procurement: Total Line Items, LLTP Ordered, LLTP Released/Ordered/Delivered Late, Parts Released/Ordered Late |
| R | 18 | Include (Y/N) |
| S/T | 19/20 | Year-Week (`2026-29`) / YearWeekKey (`202629`) |
| U | 21 | 1-Week Delta, % Done |
| V | 22 | 1-Week Delta, Materials |
| W | 23 | Total Material Budget |
| X/Y | 24/25 | Rank / Re-Rank |

Note: the pack tracks **1-week** deltas here (the dashboard's "2-Week Delta" block
should be reconciled to this — likely 1-week, or computed across two weekly rows).

---

## Consumption rules

- **Never write into this pack** — it has charts (Project Dashboard ×7, Calculations
  ×8) and Excel Tables that openpyxl does not round-trip. Read inputs; write the
  dashboard to a **separate** file (`console_dashboard.run` forces this when it
  detects Budgets + PM Entries).
- Manual layer = Budgets (discipline budget hrs AW:BA + ship dates) merged with PM
  Entries (selected week: % done, run-outs, material act/budget, procurement, deltas,
  rank). ETO supplies all actuals. `console_pack.read_pack_overlay()` returns the
  merged overlay the dashboard consumes.
- Run-out labour now prefers the **PM's entered** value (PM Entries H) over the
  naive derived one.
