# Project Console

A project-controls reporting layer for Total ETO — automates cost/budget and schedule
tracking on engineering-to-order capital projects (executive + project dashboards,
forward exposure, mitigation). Reads Total ETO **read-only**; all logic and data live in
a customer-owned Reporting database. Built to lift-and-shift to any Total ETO deployment
via a tenant profile.

## Layout
```
project-console/
├── console_config.py     Tenant profile (TenantProfile) — all per-customer settings
├── console_feed.py       ETO→discipline feed: DISCIPLINE_MAP crosswalk + Labor Data
├── console_engine.py     Analytics engine (Layer 1): est-vs-act, discipline hours, 2-wk labour
├── console_pack.py       Reads the management workbook (Budgets + PM Entries tabs)
├── console_store.py      Persistence seam: eto_connection (read-only) + console_connection;
│                         the store is swappable (SQL Server → Postgres/cloud) here
├── console_budgets.py    Seeded Budgets-input form (deferred; prototype for the web UI)
├── console_dashboard.py  Executive Dashboard builder + CLI
├── console_sync.py       ETL: spreadsheet → Console store (SCD-2 budgets, weekly PM, history)
├── console_web/          Interactive web query interface (Flask)
│   ├── queries.py        Named queries → generic QueryResult (live DAOs + demo backend)
│   ├── exporters.py      QueryResult → branded Excel (openpyxl) / PDF (reportlab)
│   ├── app.py            Flask routes (query, projects, export) + `--demo`
│   └── templates/        Single-page UI (query picker, results, Excel/PDF buttons)
├── console_test.py       Synthetic verification (no DB)
├── console_diag_*.py     Read-only schema/recon probes
├── sql/
│   ├── 001_create_macrodyne_reporting.sql   Console DB: tables + views (Macrodyne-owned)
│   └── 002_project_snapshot.sql             Weekly history/trajectory layer (prediction training)
└── tenant_macrodyne.json Sample tenant profile
```

## Architecture — Python is the only bridge
The Console DB holds **only our data** (budgets, PM, crosswalk, history) and has **no link
to ETO**. Python bridges the two over **two separate connections** (`console_store`):
- `eto_connection()` — READ-ONLY to the vendor ETO SQL Server; reads timecard actuals,
  estimating views. The engine applies the crosswalk in Python.
- `console_connection()` — read/write to the Console store.

So the Console login needs no vendor-DB access, and the store technology is swappable
(SQL Server today; Postgres/cloud for a future SaaS — reimplement `console_store`, nothing
else changes). The vendor database is never written to. The existing `eto_*` reporting
suite (Productivity, Purchase, NC) is a separate consumer of ETO and is unaffected.

## Data model
- `Reporting.*` (customer-owned): tblProjectBudget (versioned SCD-2) + Detail,
  tblProjectPMEntry (weekly), tlkpDisciplineCrosswalk, **tblProjectWeeklySnapshot**
  (per-project-per-week history — the training table for prediction models); views vw_Console_*.

## Deploy (per tenant)
1. Edit a tenant profile (see tenant_macrodyne.json); set names/DB/fiscal/scheme.
2. Run sql/001 then sql/002 as a customer-controlled sysadmin.
3. Create the customer-owned owner + service login (write on the Console DB only).
4. Copy `.env.example` to `.env` and fill in the Console store login
   (`CONSOLE_STORE_USER`/`PWD`) + ETO read login (`ETO_USER`/`PWD`). `.env` is
   gitignored and auto-loaded at startup — secrets never live in the repo or a profile.
5. `python console_sync.py --pack "<workbook>.xlsx" --dry-run`  then without --dry-run.
6. `python console_dashboard.py --workbook "<workbook>.xlsx" --projects <ids>`

## Run without a DB (today)
`python console_dashboard.py --workbook "<pack>.xlsx" --projects <ids>` reads the pack's
Budgets + PM Entries directly and writes a separate `*_AUTO.xlsx` (pack untouched).

## Web reporting suite
An interactive browser front-end — the front door to the whole reporting suite. The sidebar
groups reports into **families**:

- **Project Console** — the **Executive Dashboard** (mirrors the management workbook 1:1: the
  ranked-row-per-project board with Schedule / Budget / 2-Week Delta / Labour-by-discipline /
  Procurement blocks, group bands, frozen leading columns and amber/red traffic lights, live
  from ETO), plus Project Scorecard, Discipline Financials, Budget vs Actual and the Crosswalk.
- **Labour** — Summary (hours & applied-rate cost by project/department) + timecard-level Detail
  (`vwTimecards`).
- **Purchase** — Summary (PO commitment by vendor) + PO line Detail
  (`vwPurchaseOrderHeader`/`Details`, active POs, `ExtendedPrice`).
- **Non-Conformance** — Summary (NCR counts by source, open vs closed) + NCR Detail
  (`vwNonConformances`; status from the `Resolved` bit, PO via LEFT JOIN).

Pick projects (and an optional date range), see results, and pull an **Excel or PDF** of exactly
what's on screen. The three ETO families read the vendor **views read-only**, scoped to the
selected projects, kept in **separate queries** per the fan-out rule (never join
timecards↔PO↔NCR). **Drill-down:** click a project on the Executive Dashboard to jump straight
into that project's Labour / Purchase / Non-Conformance. It's a thin layer:
`console_web/queries.py` composes the DAOs / `ProjectFinancialsService` + the ETO views into a
generic `QueryResult`, `exporters.py` renders any `QueryResult` to xlsx/pdf, `app.py` serves them.
Adding a report is one function; the UI and exporters need no change.
```
python -m console_web.app            # live — reads the Console store + ETO (read-only)
python -m console_web.app --demo     # canned data, no database (eval / screenshots)
```
Each request builds a fresh service so DB connections never outlive the request; the store
stays swappable for the future SaaS path.

**Configurable labels.** The model keeps the canonical terms (`discipline`, `crosswalk`, …),
but every UI/column/export *label* comes from the tenant profile's `lexicon`, so a customer can
match its own nomenclature (e.g. `"discipline":"Trade"`, `"crosswalk":"Mapping"`,
`"material":"Procurement"`). Override only the terms you want; the rest keep their defaults.

## Dependencies
pandas, pyodbc, openpyxl, flask, reportlab. Python 3.10+.

## Notes
- Full design docs (architecture, DB schema design, pack schema, roadmap) live in the
  "Office Infra" project on claude.ai.
- Product core is tenant-agnostic; everything customer-specific is in the tenant profile.
