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
4. `set MACRODYNE_REPORTING_USER=... & set MACRODYNE_REPORTING_PWD=...` (Console login);
   ETO read uses its own read-only creds.
5. `python console_sync.py --pack "<workbook>.xlsx" --dry-run`  then without --dry-run.
6. `python console_dashboard.py --workbook "<workbook>.xlsx" --projects <ids>`

## Run without a DB (today)
`python console_dashboard.py --workbook "<pack>.xlsx" --projects <ids>` reads the pack's
Budgets + PM Entries directly and writes a separate `*_AUTO.xlsx` (pack untouched).

## Dependencies
pandas, pyodbc, openpyxl. Python 3.10+.

## Notes
- Full design docs (architecture, DB schema design, pack schema, roadmap) live in the
  "Office Infra" project on claude.ai.
- Product core is tenant-agnostic; everything customer-specific is in the tenant profile.
