# Project Console — Product Architecture & Lift-and-Shift Principles

**Owner:** Vijay Nair · **Set:** 2026-07-25
**Purpose:** the north star for *how* we build from here. The destination — a reporting
product that installs alongside **any** Total ETO deployment — guides every decision, so
the system can be lifted from Macrodyne and shifted to the next customer as a config
change plus an install, not a rewrite. (Commercial/ownership terms are out of scope here;
this doc is technical.)

---

## 1. The one rule

**Product core is tenant-agnostic. Everything Macrodyne-specific lives in a tenant
profile.** If a value would differ at another Total ETO shop, it is configuration, never
a literal in the code.

Tenant-specific (→ `console_config.TenantProfile`): company name/branding, ETO + Reporting
server/DB names, auth, fiscal-year start, pay-period anchor, project-number scheme, active-
project rule, output paths, dashboard week, discipline set.
Product core (identical everywhere): the Reporting schema, the ETO connector contract, the
Layer-1/2/3 engine, the Asset Re-Code *mechanism* (values are per-tenant data in the DB),
the dashboard assembly + rendering, the sync ETL.

## 2. The connector contract (the only coupling to ETO)

The product reads Total ETO **only** through the read-only `ETO.*` synonyms
(`002_eto_interface.sql`) — ~14 vendor views, SELECT-only. This is the product's
"plug." It means:
- The product installs against any ETO instance by re-pointing the synonyms.
- No product logic ever lives in the vendor database — the vendor cannot see or copy it.
- The coupling is small, documented, and auditable.

**Never** deploy a proprietary view/proc/table into the vendor DB. All product objects
live in the tenant's own `*_Reporting` database.

## 3. The DB is the tenant-agnostic data layer

The spreadsheet (Budgets + PM Entries) is a **Macrodyne artifact**, not the product. The
product's stable inputs are the Reporting views (`vw_Console_ManualOverlay`,
`vw_Console_LabourByDiscipline`). Once a tenant is on the DB, the spreadsheet reader
(`console_pack.py`) is just that tenant's *loader*; another tenant might load budgets/PM
a different way (their own sheet, or the future web UI) into the same tables. The dashboard
never cares — it reads the views.

## 4. Ownership & isolation (carry forward)

- The Reporting DB, both schemas, and the service login are owned by a **customer-controlled
  principal** — never the ETO vendor account. (For Macrodyne: not `totaletoadmin`.)
- Reporting DB lives on customer-administered infrastructure. Same instance is fine when the
  customer admins it; otherwise a customer-owned instance + read-only linked server.
- Vendor DB stays strictly SELECT-only.

## 5. Deploying to a new tenant (the lift-and-shift)

1. Write a tenant profile (`tenant_<name>.json`) — names, DB, fiscal, scheme, branding.
2. Run `001_create_<tenant>_reporting.sql` and `002_eto_interface.sql` (DB/synonym names
   come from the profile).
3. Create the customer-owned owner + service login; grant read-only on their ETO DB.
4. Point the profile's connection at their instance; run `console_sync` to load their
   budgets/PM (from their sheet or source) + seed the crosswalk from their grouping.
5. Run the dashboard — it reads their Reporting views. Done.

No code changes — only the profile and the SQL object names differ.

## 6. Anti-patterns (things that break lift-and-shift — don't do them)

- Hard-coding company name, DB names, server, paths, project numbers, or the project list
  in code. → tenant profile.
- Putting product logic (views/procs) in the vendor `dbo` database. → Reporting DB only.
- Assuming Macrodyne's fiscal calendar / pay-period / project ranges. → profile.
- Baking the Asset Re-Code values into code as the source of truth. → per-tenant, derived
  from their Budgets grouping into `Reporting.tlkpDisciplineCrosswalk`.
- One-off scripts that only run against Macrodyne's paths/sheet. → parameterise.

## 7. Migration state (what's already tenant-agnostic vs still to parameterise)

- ✅ Reporting schema, ETO connector, sync ETL structure, crosswalk-in-DB, read-only isolation.
- ✅ Sync connection is env-driven.
- ⏳ To move into the tenant profile: company name/branding (currently literals in
  `console_dashboard`/`eto_config`), project scheme + project list (`console_engine.
  VALIDATION_PROJECTS`, number ranges), fiscal/pay-period (`eto_config`), DB/server names in
  the SQL scripts. `console_config.TenantProfile` is the destination for all of these.
