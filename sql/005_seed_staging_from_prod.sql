-- ============================================================================
-- 005_seed_staging_from_prod.sql
-- Populate the STAGING store's budget tables from PROD, so PM testing starts
-- from real data.
--
--   PROD  source : Macrodyne_Reporting            (read)
--   STAGING dest : Macrodyne_Reporting_Staging     (overwritten)
--   Same server (MACRO-ETO-SVR\SQLEXPRESS), so 3-part names work.
--
-- Copies:  tlkpDisciplineCrosswalk  (needed for discipline roll-ups)
--          tblProjectBudget         (SCD-2 header, incl. LatePenalty, IsCurrent)
--          tblProjectBudgetDetail   (per-HourDescription hours)
-- PM entries are copied too but commented (section 4) — enable if you want them.
--
-- Run as a MACRODYNE SYSADMIN (needs read on prod + write on staging in one
-- session — the app's MacrodyneConsoleSvc login is staging-only by design and
-- can't do this cross-DB copy). Safe to re-run: it truncates/reloads staging.
-- It does NOT touch prod. No vendor database is referenced.
-- ============================================================================
SET NOCOUNT ON;
USE Macrodyne_Reporting_Staging;
GO

------------------------------------------------------------------------------
-- Guard: prod must exist on this server.
------------------------------------------------------------------------------
IF DB_ID('Macrodyne_Reporting') IS NULL
BEGIN
    RAISERROR('Macrodyne_Reporting (prod) not found on this server — nothing to seed from.', 16, 1);
    RETURN;
END
GO

BEGIN TRANSACTION;

------------------------------------------------------------------------------
-- 1. Clear staging budget data (detail first — FK to header).
------------------------------------------------------------------------------
DELETE FROM Reporting.tblProjectBudgetDetail;
DELETE FROM Reporting.tblProjectBudget;
DELETE FROM Reporting.tlkpDisciplineCrosswalk;

------------------------------------------------------------------------------
-- 2. Discipline crosswalk (HourDescription -> Discipline).
------------------------------------------------------------------------------
INSERT INTO Reporting.tlkpDisciplineCrosswalk (HourDescription, Discipline, UpdatedAt)
SELECT HourDescription, Discipline, UpdatedAt
FROM   Macrodyne_Reporting.Reporting.tlkpDisciplineCrosswalk;
PRINT CONCAT('crosswalk rows:  ', @@ROWCOUNT);

------------------------------------------------------------------------------
-- 3. Budget header — preserve BudgetVersionID so detail FK + IsCurrent align.
------------------------------------------------------------------------------
SET IDENTITY_INSERT Reporting.tblProjectBudget ON;
INSERT INTO Reporting.tblProjectBudget
    (BudgetVersionID, ProjectID, EffectiveFrom, EffectiveTo, IsCurrent, Source,
     POShipDate, CustAgreedShipDate, LatePenalty, MaterialBudget, LabourBudgetHours,
     PMHours, MechanicalHours, ElectricalHours, HydraulicHours, ManufacturingHours,
     OtherHours, CreatedAt, CreatedBy)
SELECT
     BudgetVersionID, ProjectID, EffectiveFrom, EffectiveTo, IsCurrent, Source,
     POShipDate, CustAgreedShipDate, LatePenalty, MaterialBudget, LabourBudgetHours,
     PMHours, MechanicalHours, ElectricalHours, HydraulicHours, ManufacturingHours,
     OtherHours, CreatedAt, CreatedBy
FROM Macrodyne_Reporting.Reporting.tblProjectBudget;
SET IDENTITY_INSERT Reporting.tblProjectBudget OFF;
PRINT CONCAT('budget headers:  ', @@ROWCOUNT);

------------------------------------------------------------------------------
-- 4. Budget detail.
------------------------------------------------------------------------------
INSERT INTO Reporting.tblProjectBudgetDetail (BudgetVersionID, HourDescription, BudgetHours)
SELECT BudgetVersionID, HourDescription, BudgetHours
FROM   Macrodyne_Reporting.Reporting.tblProjectBudgetDetail;
PRINT CONCAT('budget detail:   ', @@ROWCOUNT);

------------------------------------------------------------------------------
-- 5. OPTIONAL — weekly PM entries. Uncomment to bring these over too.
------------------------------------------------------------------------------
-- DELETE FROM Reporting.tblProjectPMEntry;
-- SET IDENTITY_INSERT Reporting.tblProjectPMEntry ON;
-- INSERT INTO Reporting.tblProjectPMEntry
--     (PMEntryID, ProjectID, FiscalYear, WeekNo, YearWeekKey, PlannedShipDate, PercentComplete,
--      LabourRunout, MaterialRunout, MaterialActual, MaterialBudget, TotalLineItems,
--      LLTPOrdered, LLTPReleasedLate, LLTPOrderedLate, LLTPDeliveredLate, PartsReleasedLate,
--      PartsOrderedLate, Delta1WkPercentDone, Delta1WkMaterial, IncludeFlag, Rank, ReRank, CapturedAt)
-- SELECT
--      PMEntryID, ProjectID, FiscalYear, WeekNo, YearWeekKey, PlannedShipDate, PercentComplete,
--      LabourRunout, MaterialRunout, MaterialActual, MaterialBudget, TotalLineItems,
--      LLTPOrdered, LLTPReleasedLate, LLTPOrderedLate, LLTPDeliveredLate, PartsReleasedLate,
--      PartsOrderedLate, Delta1WkPercentDone, Delta1WkMaterial, IncludeFlag, Rank, ReRank, CapturedAt
-- FROM Macrodyne_Reporting.Reporting.tblProjectPMEntry;
-- SET IDENTITY_INSERT Reporting.tblProjectPMEntry OFF;
-- PRINT CONCAT('pm entries:      ', @@ROWCOUNT);

COMMIT TRANSACTION;
GO

------------------------------------------------------------------------------
-- 6. Verify — staging vs prod row counts should match.
------------------------------------------------------------------------------
SELECT 'crosswalk' AS tbl,
       (SELECT COUNT(*) FROM Reporting.tlkpDisciplineCrosswalk) AS staging,
       (SELECT COUNT(*) FROM Macrodyne_Reporting.Reporting.tlkpDisciplineCrosswalk) AS prod
UNION ALL
SELECT 'budget_header',
       (SELECT COUNT(*) FROM Reporting.tblProjectBudget),
       (SELECT COUNT(*) FROM Macrodyne_Reporting.Reporting.tblProjectBudget)
UNION ALL
SELECT 'budget_detail',
       (SELECT COUNT(*) FROM Reporting.tblProjectBudgetDetail),
       (SELECT COUNT(*) FROM Macrodyne_Reporting.Reporting.tblProjectBudgetDetail);
GO
